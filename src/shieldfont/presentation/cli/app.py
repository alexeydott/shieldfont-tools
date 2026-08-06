"""Typer application and global command options."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from shieldfont import __version__
from shieldfont.application.build import build_project
from shieldfont.application.css import CssBuildOptions, CssFace, build_css
from shieldfont.application.dictionary import (
    load_and_merge,
    load_and_normalize,
    policy_from_options,
    write_dictionary_artifacts,
)
from shieldfont.application.features import (
    generate_feature_artifacts,
    load_scope_from_ruleset,
    opaque_source_glyph_name,
)
from shieldfont.application.font import inspect_font, normalize_font, unpack_font
from shieldfont.application.init_project import InitRequest, initialize_project
from shieldfont.application.llm_dictionary import (
    generate_candidate_dictionary,
    review_and_export,
)
from shieldfont.application.migrate import migrate_legacy_project
from shieldfont.application.verify import (
    verify_font,
    verify_manifest,
    verify_reports,
    verify_shaping_samples,
)
from shieldfont.application.web import WebActions
from shieldfont.config.loader import load_config
from shieldfont.domain.dictionary.models import DictionaryPolicy
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import ReviewStatus
from shieldfont.infrastructure.font import inspect_font_for_init
from shieldfont.infrastructure.llm_dictionary.provider import JsonFileCandidateProvider
from shieldfont.infrastructure.logging import (
    LogFormat,
    configure_logging,
    log_event,
    resolve_log_settings,
)
from shieldfont.presentation.web.server import ServerConfig, serve

app = typer.Typer(
    name="shieldfont",
    help="Build and verify multilingual TrueType ShieldFont assets.",
    no_args_is_help=True,
    add_completion=False,
)
dictionary_app = typer.Typer(
    name="dict",
    help="Validate, normalize, and merge mapping dictionaries.",
    no_args_is_help=True,
    add_completion=False,
)
font_app = typer.Typer(
    name="font",
    help="Inspect and unpack TrueType source fonts.",
    no_args_is_help=True,
    add_completion=False,
)
features_app = typer.Typer(
    name="features",
    help="Generate deterministic OpenType feature source.",
    no_args_is_help=True,
    add_completion=False,
)
css_app = typer.Typer(
    name="css",
    help="Generate CSS delivery assets.",
    no_args_is_help=True,
    add_completion=False,
)
migrate_app = typer.Typer(
    name="migrate",
    help="Migrate supported legacy ShieldFont projects.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(dictionary_app, name="dict")
app.add_typer(font_app, name="font")
app.add_typer(features_app, name="features")
app.add_typer(css_app, name="css")
app.add_typer(migrate_app, name="migrate")

LOGGER = logging.getLogger("shieldfont.cli")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _parse_scripts(value: str) -> tuple[str, ...]:
    scripts = tuple(part.strip() for part in value.split(",") if part.strip())
    invalid = [script for script in scripts if len(script) != 4]
    if not scripts or invalid:
        raise ShieldFontError(
            "OpenType scripts must be a comma-separated list of four-character tags",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="init.arguments",
            details={"invalid": invalid},
        )
    return scripts


@app.callback()
def configure_cli(
    log_format: Annotated[
        LogFormat,
        typer.Option("--log-format", help="Render logs as text or JSON."),
    ] = LogFormat.TEXT,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", help="Suppress non-fatal logs."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable DEBUG logs."),
    ] = False,
    trace: Annotated[
        bool,
        typer.Option("--trace", help="Enable detailed DEBUG logs."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the tool version and exit.",
        ),
    ] = False,
) -> None:
    """Configure process-wide diagnostics before dispatching a command."""

    del version
    settings = resolve_log_settings(
        log_format=log_format,
        quiet=quiet,
        verbose=verbose,
        trace=trace,
    )
    configure_logging(settings)
    log_event(
        LOGGER,
        logging.DEBUG,
        "CLI logging configured",
        code="SF-CLI-CONFIGURED",
        stage="cli.configure",
        details={
            "format": settings.format.value,
            "level": logging.getLevelName(settings.level),
            "enabled": settings.enabled,
        },
    )


@app.command("init")
def init_command(
    project_dir: Annotated[
        Path,
        typer.Argument(help="Directory in which to create the project."),
    ] = Path("."),
    font: Annotated[
        Path | None,
        typer.Option("--font", help="TrueType TTF or WOFF2 source font."),
    ] = None,
    family: Annotated[
        str | None,
        typer.Option("--family", help="Output font family name."),
    ] = None,
    postfix: Annotated[
        str,
        typer.Option(
            "--postfix",
            help="Suffix appended to the source font family name.",
        ),
    ] = "_shld",
    scripts: Annotated[
        str,
        typer.Option("--scripts", help="Comma-separated OpenType script tags."),
    ] = "DFLT",
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing shieldfont.yml."),
    ] = False,
) -> None:
    """Create a ShieldFont Toolchain project template."""

    config_path = initialize_project(
        InitRequest(
            project_dir=project_dir,
            font_path=font,
            family=family,
            postfix=postfix,
            scripts=_parse_scripts(scripts),
            force=force,
        ),
        inspect_font=inspect_font_for_init,
    )
    typer.echo(config_path)


@font_app.command("inspect")
def font_inspect_command(
    input_path: Annotated[Path, typer.Argument(help="TTF or WOFF2 source font.")],
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Enable strict diagnostic checks."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Inspect a source font and report outlines, layout, names, and coverage."""

    inspection = inspect_font(input_path, strict=strict)
    if json_output:
        typer.echo(json.dumps(inspection.to_dict(), ensure_ascii=False, sort_keys=True))
        return
    typer.echo(f"path: {inspection.path}")
    typer.echo(f"container: {inspection.container}")
    typer.echo(f"outlines: {'glyf' if inspection.has_glyf else 'unsupported'}")
    typer.echo(f"glyphs: {inspection.glyph_count}")
    typer.echo(f"tables: {', '.join(inspection.tables)}")
    if inspection.warnings:
        typer.echo(f"warnings: {'; '.join(inspection.warnings)}")


@font_app.command("unpack")
def font_unpack_command(
    input_path: Annotated[Path, typer.Argument(help="TTF or WOFF2 source font.")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Diagnostic output directory."),
    ] = Path("unpacked"),
) -> None:
    """Write a diagnostic decomposition of a source font."""

    typer.echo(unpack_font(input_path, output_dir))


@font_app.command("normalize")
def font_normalize_command(
    input_path: Annotated[Path, typer.Argument(help="TTF or WOFF2 source font.")],
    output_path: Annotated[
        Path,
        typer.Argument(help="Static normalized TTF output."),
    ],
    family: Annotated[str, typer.Option("--family")],
    subfamily: Annotated[str, typer.Option("--subfamily")] = "Regular",
    post_script_name: Annotated[
        str | None,
        typer.Option("--post-script-name"),
    ] = None,
    named_instance: Annotated[
        str | None,
        typer.Option("--named-instance"),
    ] = None,
    axes: Annotated[
        str | None,
        typer.Option("--axes", help="Comma-separated axis=value pairs."),
    ] = None,
    license_policy: Annotated[
        str,
        typer.Option("--license-policy", help="warn, error, or ignore."),
    ] = "warn",
) -> None:
    """Create a static, renamed, and license-checked TrueType derivative."""

    coordinates: dict[str, float] = {}
    if axes:
        for item in axes.split(","):
            key, separator, value = item.partition("=")
            if not separator or not key.strip():
                raise ShieldFontError(
                    "Axes must use tag=value pairs",
                    code=ErrorCode.INVALID_INPUT,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="font.normalize.arguments",
                    details={"axes": axes},
                )
            try:
                coordinates[key.strip()] = float(value)
            except ValueError as error:
                raise ShieldFontError(
                    "Font axis coordinate must be numeric",
                    code=ErrorCode.INVALID_INPUT,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="font.normalize.arguments",
                    details={"axis": key.strip(), "value": value},
                ) from error
    if license_policy not in {"warn", "error", "ignore"}:
        raise ShieldFontError(
            "Unsupported license policy",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="font.normalize.arguments",
            details={"licensePolicy": license_policy},
        )
    result = normalize_font(
        input_path,
        output_path,
        family=family,
        subfamily=subfamily,
        post_script_name=post_script_name,
        axes=coordinates or None,
        named_instance=named_instance,
        license_policy=license_policy,
    )
    typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


@features_app.command("generate")
def features_generate_command(
    ruleset_path: Annotated[
        Path,
        typer.Argument(help="Canonical ruleset JSON."),
    ],
    scope_id: Annotated[
        str,
        typer.Option("--scope", help="Scope identifier to generate."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Feature artifact directory."),
    ] = Path("dist/features"),
    stem: Annotated[str, typer.Option("--stem")] = "shieldfont",
) -> None:
    """Generate fire-then-revert .fea and layout-plan artifacts."""

    scope = load_scope_from_ruleset(ruleset_path, scope_id)
    artifacts = generate_feature_artifacts(
        scope,
        glyph_for_target=lambda character: f"uni{ord(character):04X}",
        glyph_for_source=lambda source: opaque_source_glyph_name(scope_id, source),
        output_dir=output_dir,
        stem=stem,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in artifacts.items()},
            sort_keys=True,
        )
    )


@css_app.command("build")
def css_build_command(
    output_path: Annotated[
        Path,
        typer.Argument(help="CSS output path."),
    ],
    family: Annotated[str, typer.Option("--family")],
    shield_font: Annotated[str, typer.Option("--shield-font")],
    neutral_font: Annotated[
        str | None,
        typer.Option("--neutral-font"),
    ] = None,
    neutral_family: Annotated[
        str | None,
        typer.Option("--neutral-family"),
    ] = None,
    asset_base_url: Annotated[
        str,
        typer.Option("--asset-base-url"),
    ] = "./fonts/",
    font_display: Annotated[str, typer.Option("--font-display")] = "block",
    include_ttf_fallback: Annotated[
        bool,
        typer.Option("--include-ttf-fallback"),
    ] = False,
) -> None:
    """Generate shield/neutral @font-face rules and SRI metadata."""

    neutral = (
        CssFace(neutral_family or f"{family} Text", neutral_font)
        if neutral_font
        else None
    )
    artifacts = build_css(
        CssFace(family, shield_font),
        neutral_face=neutral,
        options=CssBuildOptions(
            asset_base_url=asset_base_url,
            font_display=font_display,
            include_ttf_fallback=include_ttf_fallback,
        ),
        output_path=output_path,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in artifacts.items()},
            sort_keys=True,
        )
    )


@app.command("build")
def build_command(
    config_path: Annotated[
        Path,
        typer.Option("--config", help="ShieldFont YAML configuration."),
    ] = Path("shieldfont.yml"),
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Override configured output directory."),
    ] = None,
) -> None:
    """Run implemented build stages and atomically publish dist artifacts."""

    typer.echo(build_project(config_path, output_dir=output_dir))


@app.command("serve")
def serve_command(
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="Project root containing shieldfont.yml."),
    ] = Path("."),
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address; defaults to localhost."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535),
    ] = 8765,
    static_root: Annotated[
        Path | None,
        typer.Option("--static-root", help="Override the GUI static asset root."),
    ] = None,
    fonts_root: Annotated[
        Path,
        typer.Option(
            "--fonts-dir",
            "--fonts-root",
            help="Project-relative directory from which source fonts are selected.",
        ),
    ] = Path(".fonts"),
) -> None:
    """Serve the local ShieldFont GUI and safe application actions."""

    root = project_root.resolve()
    config = load_config(root / "shieldfont.yml")
    actions = WebActions(root, fonts_root)
    source_path = config.source.path
    if not source_path.is_absolute():
        source_path = root / source_path
    if source_path.is_file():
        generated_output = build_project(root / "shieldfont.yml")
        typer.echo(f"Generated fresh server artifacts in {generated_output}")
    else:
        typer.echo(
            f"Source font {source_path} is unavailable; starting the GUI without "
            "prebuilt artifacts."
        )
    serve(
        ServerConfig(
            project_root=root,
            host=host,
            port=port,
            static_root=static_root,
            fonts_root=fonts_root,
        ),
        actions,
    )


@app.command("verify")
def verify_command(
    root: Annotated[
        Path,
        typer.Argument(help="Build or font path to verify."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Verification report directory."),
    ] = Path("dist/reports"),
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Enable strict font checksum checks."),
    ] = True,
    positive_sample: Annotated[
        list[str] | None,
        typer.Option("--positive-sample", help="Positive HarfBuzz shaping sample."),
    ] = None,
    negative_sample: Annotated[
        list[str] | None,
        typer.Option("--negative-sample", help="Negative HarfBuzz shaping sample."),
    ] = None,
) -> None:
    """Run structural and manifest verification and write JSON/HTML reports."""

    if root.suffix.lower() in {".ttf", ".woff2"}:
        report = verify_font(root, strict=strict)
        if positive_sample or negative_sample:
            shaping_report = verify_shaping_samples(
                root,
                positive=tuple(positive_sample or ()),
                negative=tuple(negative_sample or ()),
            )
            report.checks.update(shaping_report.checks)
            report.warnings.extend(shaping_report.warnings)
            for error in shaping_report.errors:
                report.fail("shaping", error)
    else:
        report = verify_manifest(root)
    artifacts = verify_reports(report, output_dir)
    if report.status == "fail":
        raise ShieldFontError(
            "Verification failed",
            code=ErrorCode.SHAPING_VERIFICATION_ERROR,
            exit_code=ExitCode.SHAPING_VERIFICATION_ERROR,
            stage="verify",
            details={"errors": report.errors},
        )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in artifacts.items()},
            sort_keys=True,
        )
    )


@migrate_app.command("legacy-project")
def migrate_legacy_project_command(
    mapping: Annotated[
        Path,
        typer.Option("--mapping", exists=True, readable=True),
    ],
    font: Annotated[
        Path,
        typer.Option("--font"),
    ],
    out: Annotated[
        Path,
        typer.Option("--out"),
    ],
) -> None:
    """Migrate a flat legacy JSON mapping into a scoped project."""

    artifacts = migrate_legacy_project(
        mapping_path=mapping,
        font_path=font,
        output_dir=out,
    )
    typer.echo(json.dumps({key: str(value) for key, value in artifacts.items()}))


def _dictionary_policy(
    mapping_mode: str,
    duplicate_policy: str,
    target_collision_policy: str,
    self_map_policy: str,
) -> DictionaryPolicy:
    return policy_from_options(
        mapping_mode=mapping_mode,
        duplicate_policy=duplicate_policy,
        target_collision_policy=target_collision_policy,
        self_map_policy=self_map_policy,
    )


@dictionary_app.command("validate")
def dictionary_validate_command(
    inputs: Annotated[
        list[Path],
        typer.Argument(..., help="CSV dictionaries to validate."),
    ],
    mapping_mode: Annotated[
        str,
        typer.Option(
            "--mapping-mode",
            help="involution, bidirectional, or one-way mode.",
        ),
    ] = "involution",
    duplicate_policy: Annotated[
        str,
        typer.Option("--duplicate-policy", help="error, first-wins, or last-wins."),
    ] = "error",
    target_collision_policy: Annotated[
        str,
        typer.Option("--target-collision-policy", help="Policy for duplicate targets."),
    ] = "error",
    self_map_policy: Annotated[
        str,
        typer.Option("--self-map-policy", help="error or drop-with-warning."),
    ] = "drop-with-warning",
) -> None:
    """Validate dictionaries and print deterministic statistics."""

    dictionary = load_and_normalize(
        inputs,
        policy=_dictionary_policy(
            mapping_mode,
            duplicate_policy,
            target_collision_policy,
            self_map_policy,
        ),
    )
    typer.echo(
        json.dumps(
            {
                "entries": len(dictionary.entries),
                "warnings": list(dictionary.warnings),
                "mappingHash": dictionary.mapping_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@dictionary_app.command("normalize")
def dictionary_normalize_command(
    inputs: Annotated[
        list[Path],
        typer.Argument(..., help="CSV dictionaries to normalize."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for canonical artifacts."),
    ] = Path("dist"),
    stem: Annotated[
        str,
        typer.Option("--stem", help="Artifact filename stem."),
    ] = "canonical",
    mapping_mode: Annotated[str, typer.Option("--mapping-mode")] = "involution",
    duplicate_policy: Annotated[str, typer.Option("--duplicate-policy")] = "error",
    target_collision_policy: Annotated[
        str,
        typer.Option("--target-collision-policy"),
    ] = "error",
    self_map_policy: Annotated[
        str,
        typer.Option("--self-map-policy"),
    ] = "drop-with-warning",
) -> None:
    """Normalize dictionaries and emit canonical mapping artifacts."""

    dictionary = load_and_normalize(
        inputs,
        policy=_dictionary_policy(
            mapping_mode,
            duplicate_policy,
            target_collision_policy,
            self_map_policy,
        ),
    )
    artifacts = write_dictionary_artifacts(
        dictionary,
        output_dir=output_dir,
        stem=stem,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in artifacts.items()},
            sort_keys=True,
        )
    )


@dictionary_app.command("merge")
def dictionary_merge_command(
    inputs: Annotated[
        list[Path],
        typer.Argument(..., help="CSV dictionaries in base-to-override order."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for canonical artifacts."),
    ] = Path("dist"),
    stem: Annotated[str, typer.Option("--stem")] = "merged",
    deny: Annotated[
        list[str] | None,
        typer.Option("--deny", help="Source or target value to exclude; repeatable."),
    ] = None,
    mapping_mode: Annotated[str, typer.Option("--mapping-mode")] = "involution",
    duplicate_policy: Annotated[str, typer.Option("--duplicate-policy")] = "error",
    target_collision_policy: Annotated[
        str,
        typer.Option("--target-collision-policy"),
    ] = "error",
    self_map_policy: Annotated[
        str,
        typer.Option("--self-map-policy"),
    ] = "drop-with-warning",
) -> None:
    """Merge layered dictionaries and emit canonical mapping artifacts."""

    dictionary = load_and_merge(
        inputs,
        policy=_dictionary_policy(
            mapping_mode,
            duplicate_policy,
            target_collision_policy,
            self_map_policy,
        ),
        deny=deny or (),
    )
    artifacts = write_dictionary_artifacts(
        dictionary,
        output_dir=output_dir,
        stem=stem,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in artifacts.items()},
            sort_keys=True,
        )
    )


@dictionary_app.command("from-text")
def dictionary_from_text_command(
    inputs: Annotated[
        list[Path],
        typer.Argument(..., help="Text, Markdown, or HTML corpus files."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Candidate artifact directory."),
    ] = Path("dictionaries/generated"),
    scope: Annotated[str, typer.Option("--scope")] = "default",
    responses: Annotated[
        Path | None,
        typer.Option(
            "--responses",
            help="Optional local JSON response fixture; no network is used.",
        ),
    ] = None,
    min_length: Annotated[int, typer.Option("--min-length", min=1)] = 2,
) -> None:
    """Extract corpus tokens and emit candidate-only LLM dictionary artifacts."""

    provider = JsonFileCandidateProvider(responses) if responses else None
    result = generate_candidate_dictionary(
        tuple(inputs),
        output_dir=output_dir,
        scope=scope,
        provider=provider,
        min_length=min_length,
    )
    typer.echo(
        json.dumps(
            {name: str(path) for name, path in result.artifacts.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@dictionary_app.command("review")
def dictionary_review_command(
    candidates: Annotated[Path, typer.Argument(help="Generated candidates CSV.")],
    decisions: Annotated[
        Path,
        typer.Option(
            "--decisions",
            help="JSON array of source/target/status decisions.",
        ),
    ],
    approved: Annotated[
        Path,
        typer.Option("--approved", help="Approved CSV output path."),
    ],
    reviewed: Annotated[
        Path | None,
        typer.Option("--reviewed", help="Reviewed candidate CSV output path."),
    ] = None,
    mapping_mode: Annotated[
        str,
        typer.Option("--mapping-mode", help="involution or directed."),
    ] = "involution",
) -> None:
    """Apply explicit review decisions and export only validated approvals."""

    payload = json.loads(decisions.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ShieldFontError(
            "Review decisions must be a JSON array",
            code=ErrorCode.LLM_VALIDATION,
            exit_code=ExitCode.LLM_VALIDATION_ERROR,
            stage="llm_dictionary.review",
        )
    resolved: dict[tuple[str, str], ReviewStatus] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ShieldFontError(
                "Review decision must be an object",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.review",
            )
        try:
            resolved[
                (str(item["source"]), str(item["target"]))
            ] = ReviewStatus(str(item["status"]))
        except (KeyError, ValueError) as error:
            raise ShieldFontError(
                "Review decision has invalid source, target, or status",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.review",
            ) from error
    reviewed_path = reviewed or candidates.with_name(
        candidates.name.replace(".candidates.csv", ".reviewed.csv")
    )
    reviewed_path, approved_path = review_and_export(
        candidates,
        resolved,
        reviewed_path=reviewed_path,
        approved_path=approved,
        mapping_mode=mapping_mode,
    )
    typer.echo(
        json.dumps(
            {"reviewed": str(reviewed_path), "approved": str(approved_path)},
            sort_keys=True,
        )
    )
