"""Atomic, reproducible build orchestration for the implemented pipeline stages."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from shieldfont import __version__
from shieldfont.application.css import CssBuildOptions, CssFace, build_css
from shieldfont.application.features import generate_feature_artifacts
from shieldfont.application.ruleset import build_ruleset_from_config
from shieldfont.config.loader import load_config
from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font_naming import (
    OUTPUT_FONT_SUBFAMILY,
    OUTPUT_TYPOGRAPHIC_FAMILY,
    output_font_filename,
    output_post_script_name,
)
from shieldfont.domain.manifest import BuildManifest
from shieldfont.domain.ruleset import ScopeRecord
from shieldfont.infrastructure.dictionary.csv_reader import read_csv_dictionary
from shieldfont.infrastructure.font.compile import (
    add_fire_then_revert_context,
    compile_feature_source,
)
from shieldfont.infrastructure.font.glyf_builder import (
    GlyfCompositeBuilder,
    opaque_glyph_name,
)
from shieldfont.infrastructure.font.inventory import inspect_font
from shieldfont.infrastructure.font.normalize import normalize_font
from shieldfont.infrastructure.font.serialize import serialize_true_type


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _write_checksums(root: Path) -> Path:
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            relative = path.relative_to(root).as_posix()
            entries.append(f"{_sha256(path)}  {relative}")
    checksums = root / "SHA256SUMS"
    checksums.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return checksums


def _publish_atomically(staging: Path, destination: Path) -> None:
    previous = destination.with_name(f"{destination.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if destination.exists():
        destination.rename(previous)
    try:
        staging.rename(destination)
    except OSError:
        if previous.exists() and not destination.exists():
            previous.rename(destination)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def build_project(
    config_path: Path,
    *,
    config_override: ShieldFontConfig | None = None,
    output_dir: Path | None = None,
    source_path: Path | None = None,
    dictionary_path: Path | None = None,
) -> Path:
    """Build available stages into a temporary tree and publish atomically."""

    config = config_override or load_config(config_path)
    selected_source_path = (source_path or config.source.path).resolve()
    selected_dictionary_path = (
        dictionary_path.resolve() if dictionary_path is not None else None
    )
    destination = (output_dir or config.project.output_dir).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            dir=str(destination.parent),
        )
    )
    try:
        inspection = inspect_font(selected_source_path, strict=True)
        dictionaries = {
            scope.id: [
                entry
                for path in (
                    [selected_dictionary_path]
                    if selected_dictionary_path is not None
                    else scope.dictionaries
                )
                for entry in read_csv_dictionary(path)
            ]
            for scope in config.scopes
        }
        ruleset = build_ruleset_from_config(config, dictionaries)
        ruleset_path = staging / "ruleset.json"
        ruleset_path.write_text(ruleset.to_json(), encoding="utf-8")
        normalized_path = staging / "normalized.ttf"
        normalize_font(
            selected_source_path,
            normalized_path,
            family=config.font.family,
            subfamily=OUTPUT_FONT_SUBFAMILY,
            post_script_name=output_post_script_name(config.font.family),
            axes=config.source.instance.axes,
            license_policy=config.license.policy,
        )
        neutral_font = TTFont(normalized_path, lazy=False)
        shield_font = TTFont(normalized_path, lazy=False)
        glyph_builder = GlyfCompositeBuilder(shield_font)
        cmap = shield_font.getBestCmap() or {}
        feature_dir = staging / "features"
        feature_plans: list[str] = []
        feature_paths: list[Path] = []
        generated_glyphs: set[str] = set()
        for scope in ruleset.scopes:
            generated: dict[str, str] = {}

            def glyph_for_target(
                character: str,
                *,
                _cmap: Mapping[int, str] = cmap,
                _scope: ScopeRecord = scope,
            ) -> str:
                glyph_name = _cmap.get(ord(character))
                if not isinstance(glyph_name, str):
                    raise ShieldFontError(
                        "Feature target contains a code point missing from cmap",
                        code=ErrorCode.FEATURE_GENERATION_ERROR,
                        exit_code=ExitCode.FEATURE_GENERATION_ERROR,
                        stage="build.features",
                        details={"scope": _scope.scope_id, "character": character},
                    )
                return glyph_name

            def glyph_for_source(
                source: str,
                *,
                _scope: ScopeRecord = scope,
                _generated: dict[str, str] = generated,
            ) -> str:
                if source not in _generated:
                    _generated[source] = opaque_glyph_name(
                        _scope.scope_id,
                        source,
                        _scope.mapping_hash,
                    )
                    glyph_builder.create_word_glyph(source, _generated[source])
                return _generated[source]

            def glyph_for_source_variant(
                source: str,
                variant: str,
                *,
                _scope: ScopeRecord = scope,
                _generated: dict[str, str] = generated,
            ) -> str:
                key = f"{variant}\0{source}"
                if key not in _generated:
                    _generated[key] = opaque_glyph_name(
                        _scope.scope_id,
                        key,
                        _scope.mapping_hash,
                    )
                    glyph_builder.create_word_glyph(source, _generated[key])
                return _generated[key]

            prefix = re.sub(r"[^A-Za-z0-9]+", "_", scope.scope_id).strip("_") or "scope"
            artifacts = generate_feature_artifacts(
                scope,
                glyph_for_target=glyph_for_target,
                glyph_for_source=glyph_for_source,
                glyph_for_source_variant=glyph_for_source_variant,
                glyph_id=shield_font.getGlyphID,
                output_dir=feature_dir,
                stem=prefix,
                lookup_prefix=f"sf_{prefix}",
            )
            generated_glyphs.update(generated.values())
            feature_paths.append(artifacts["fea"])
            feature_plans.append(artifacts["fea"].read_text(encoding="utf-8"))
        glyph_builder.finalize()
        combined_feature_path = feature_dir / "combined.fea"
        languagesystems: list[str] = []
        lookups: list[str] = []
        attached: list[str] = []
        for source in feature_plans:
            lines = source.splitlines()
            in_feature = False
            in_lookup = False
            current_lookup: list[str] = []
            for line in lines:
                if line.startswith("languagesystem ") and line not in languagesystems:
                    languagesystems.append(line)
                elif line.startswith("lookup ") and not in_feature:
                    in_lookup = True
                    current_lookup = [line]
                elif in_lookup:
                    current_lookup.append(line)
                    if line.endswith(";") and line.startswith("} "):
                        lookups.extend(current_lookup)
                        in_lookup = False
                elif line.startswith("feature ccmp {"):
                    in_feature = True
                elif in_feature and line.startswith("  lookup "):
                    attached.append(line)
                elif in_feature and line == "} ccmp;":
                    in_feature = False
        combined_feature_path.write_text(
            "\n".join(
                [
                    *languagesystems,
                    "",
                    *lookups,
                    "",
                    "feature ccmp {",
                    *dict.fromkeys(attached),
                    "} ccmp;",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        compile_feature_source(shield_font, combined_feature_path)
        add_fire_then_revert_context(
            shield_font,
            lookup_indices=(0, 1, 2, 3),
            generated_glyphs=generated_glyphs,
        )
        font_dir = staging / "fonts"
        font_artifacts: list[dict[str, str]] = []
        for extension in config.font.output_formats:
            shield_path = font_dir / output_font_filename(config.font.family, extension)
            neutral_path = font_dir / output_font_filename(
                config.font.neutral_face.family,
                extension,
            )
            serialize_true_type(shield_font, shield_path)
            if config.font.neutral_face.enabled:
                serialize_true_type(neutral_font, neutral_path)
            font_artifacts.append(
                {
                    "path": str(shield_path.relative_to(staging).as_posix()),
                    "sha256": _sha256(shield_path),
                }
            )
            if config.font.neutral_face.enabled:
                font_artifacts.append(
                    {
                        "path": str(neutral_path.relative_to(staging).as_posix()),
                        "sha256": _sha256(neutral_path),
                    }
                )
        css_artifacts = build_css(
            CssFace(
                config.font.shield_face.family,
                output_font_filename(config.font.family, "woff2"),
            ),
            neutral_face=(
                CssFace(
                    config.font.neutral_face.family,
                    output_font_filename(config.font.neutral_face.family, "woff2"),
                )
                if config.font.neutral_face.enabled
                else None
            ),
            options=CssBuildOptions(
                asset_base_url=config.css.asset_base_url,
                font_display=config.css.font_display,
                font_synthesis=config.css.font_synthesis,
                shield_class=config.css.classes.shield,
                neutral_class=config.css.classes.neutral,
                embed_font=config.css.embed_font,
            ),
            asset_root=font_dir,
            output_path=staging / "shieldfont.css",
        )
        manifest = BuildManifest.create(
            project_id=config.project.id,
            project_version=config.project.version,
            tool_version=__version__,
            source={
                "path": selected_source_path.name,
                "sha256": _sha256(selected_source_path),
                "outlineType": "glyf" if inspection.has_glyf else "unsupported",
                "variable": inspection.variable,
                "axes": inspection.axes,
            },
            font={
                "family": config.font.family,
                "subfamily": OUTPUT_FONT_SUBFAMILY,
                "typographicFamily": OUTPUT_TYPOGRAPHIC_FAMILY,
                "typographicSubfamily": OUTPUT_FONT_SUBFAMILY,
                "postScriptName": output_post_script_name(config.font.family),
                "version": config.project.version,
            },
            scopes=[
                {
                    "id": scope.scope_id,
                    "mappingHash": scope.mapping_hash,
                    "pairs": len(scope.rules),
                    "openTypeScript": scope.open_type_script,
                    "defaultLanguage": scope.default_language,
                }
                for scope in ruleset.scopes
            ],
            artifacts=[
                {"path": "ruleset.json", "sha256": _sha256(ruleset_path)},
                *font_artifacts,
                *[
                    {
                        "path": str(path.relative_to(staging).as_posix()),
                        "sha256": _sha256(path),
                    }
                    for path in [*feature_paths, combined_feature_path]
                ],
                {
                    "path": str(
                        css_artifacts["css"].relative_to(staging).as_posix()
                    ),
                    "sha256": _sha256(css_artifacts["css"]),
                },
            ],
            verification={"status": "pending"},
            security={
                "browserDecoderIncluded": config.codec.browser_build,
                "mappingEmbedded": config.codec.embed_mappings,
                "glyphNamesDroppedFromWoff2": True,
            },
        )
        (staging / "manifest.json").write_text(
            manifest.to_json(),
            encoding="utf-8",
        )
        _write_checksums(staging)
        _publish_atomically(staging, destination)
        return destination
    except ShieldFontError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ShieldFontError(
            "ShieldFont build failed before publication",
            code=ErrorCode.GENERIC,
            exit_code=ExitCode.GENERIC_FAILURE,
            stage="build",
            details={"staging": str(staging), "reason": str(error)},
        ) from error
