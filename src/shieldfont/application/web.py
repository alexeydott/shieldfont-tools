"""Application adapters exposed by the local ShieldFont web presentation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from shieldfont.application.build import build_project
from shieldfont.application.css import CssBuildOptions, CssFace, build_css
from shieldfont.application.dictionary import (
    load_and_normalize,
    policy_from_options,
    write_dictionary_artifacts,
)
from shieldfont.application.init_project import (
    ensure_default_dictionary,
    ensure_demo_corpus,
)
from shieldfont.application.verify import verify_manifest
from shieldfont.config.loader import dump_resolved_config, load_config
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font_naming import output_font_filename
from shieldfont.infrastructure.font.inventory import inspect_font
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.web.application")
_UNICODE_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _encode_test_text(
    text: str,
    rules: list[Mapping[str, Any]],
) -> tuple[str, int]:
    """Encode complete Unicode words without cascading replacements."""

    mapping = {
        str(rule["source"]).casefold(): str(rule["target"])
        for rule in rules
        if isinstance(rule.get("source"), str)
        and isinstance(rule.get("target"), str)
        and rule["source"]
    }
    applied = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal applied
        source = match.group(0)
        target = mapping.get(source.casefold())
        if target is None:
            return source
        applied += 1
        if len(source) > 1 and source.isupper():
            return target.upper()
        if source[:1].isupper():
            return target[:1].upper() + target[1:]
        return target

    return _UNICODE_WORD_RE.sub(replace, text), applied


class WebActions:
    """Dispatch the explicit safe action set to application services."""

    def __init__(
        self,
        project_root: Path,
        fonts_root: Path = Path(".fonts"),
    ) -> None:
        self.project_root = project_root.resolve()
        configured_fonts_root = (
            fonts_root if fonts_root.is_absolute() else self.project_root / fonts_root
        )
        self.fonts_root = configured_fonts_root.resolve()
        try:
            self.fonts_root.relative_to(self.project_root)
        except ValueError as error:
            raise ShieldFontError(
                "Fonts directory must be inside the project root",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.config",
            ) from error
        self.fonts_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root = self.project_root / ".shieldfont"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.default_dictionary_state = self.runtime_root / "default-dictionary"
        ensure_default_dictionary(self.project_root)
        ensure_demo_corpus(self.project_root)

    def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        log_event(
            LOGGER,
            logging.INFO,
            "Web action started",
            stage="web.action",
            details={"action": action},
        )
        result = cast(
            Callable[[Mapping[str, Any]], dict[str, Any]] | None,
            getattr(self, f"_{action.replace('-', '_')}", None),
        )
        if result is None:
            raise ShieldFontError(
                "Unsupported web action",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.action",
                details={"action": action},
            )
        value = result(payload)
        log_event(
            LOGGER,
            logging.INFO,
            "Web action completed",
            stage="web.action",
            details={"action": action},
        )
        return value

    def _build(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._config_path().is_file():
            self._load_config()
        selected_source = self._selected_source_path(payload)
        build_options: dict[str, Any] = {}
        if selected_source is not None:
            build_options["source_path"] = selected_source
            LOGGER.info(
                "[FIX] Web build source font selected",
                extra={"path": self._relative_or_name(selected_source)},
            )
        if "outputDir" in payload:
            output = build_project(
                self._config_path(),
                output_dir=self._payload_path(
                    payload,
                    "outputDir",
                    Path("dist"),
                ),
                **build_options,
            )
        else:
            output = build_project(self._config_path(), **build_options)
        result: dict[str, Any] = {"outputDir": str(output)}
        if output.is_dir():
            files = {
                "fonts": sorted(
                    str(path.relative_to(output))
                    for path in (output / "fonts").glob("*")
                    if path.is_file()
                ),
                "features": sorted(
                    str(path.relative_to(output))
                    for path in (output / "features").glob("*")
                    if path.is_file()
                ),
                "css": str((output / "shieldfont.css").relative_to(output))
                if (output / "shieldfont.css").is_file()
                else None,
                "manifest": "manifest.json"
                if (output / "manifest.json").is_file()
                else None,
                "checksums": "SHA256SUMS"
                if (output / "SHA256SUMS").is_file()
                else None,
            }
            result["artifacts"] = {
                key: value for key, value in files.items() if value not in (None, [])
            }
            codec_dist = self.project_root / "packages" / "codec" / "dist"
            if codec_dist.is_dir():
                result["bundles"] = {
                    "codec": sorted(
                        str(path.relative_to(self.project_root))
                        for path in codec_dist.rglob("*")
                        if path.is_file()
                    )
                }
        return result

    def _verify(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        del payload
        report = verify_manifest(self.project_root / "dist")
        return {"report": report.to_dict()}

    def _font_inspect(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = (
            self._font_payload_path(payload, "path")
            if "path" in payload
            else self._source_path()
        )
        return {"inspection": inspect_font(path, strict=True).to_dict()}

    def _font_upload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        filename = payload.get("filename")
        content = payload.get("content")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
        ):
            raise ShieldFontError(
                "Uploaded font filename is invalid",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        if (
            not isinstance(content, bytes)
            or not content
            or len(content) > 32 * 1024 * 1024
        ):
            raise ShieldFontError(
                "Uploaded font content is empty or too large",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        if Path(filename).suffix.lower() not in {".ttf", ".woff2"}:
            raise ShieldFontError(
                "Uploaded file must use a supported font extension",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        path = (self.fonts_root / filename).resolve()
        self._assert_font_directory(path)
        if path.is_symlink():
            raise ShieldFontError(
                "Uploaded font path may not be a symlink",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.fonts_root,
                prefix=f".{path.name}.",
                suffix=path.suffix,
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            inspection = inspect_font(temporary_path, strict=True)
            temporary_path.replace(path)
        except ShieldFontError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ShieldFontError(
                "Unable to save uploaded font",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
                details={"file": str(path), "reason": str(error)},
            ) from error
        LOGGER.info(
            "[FIX] Source font uploaded",
            extra={"path": str(path), "bytes": len(content)},
        )
        return {
            "path": self._relative_or_name(path),
            "size": len(content),
            "inspection": inspection.to_dict(),
        }

    def _font_select(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = self._font_payload_path(payload, "path")
        inspection = self._font_inspect(
            {"path": str(path.relative_to(self.project_root))}
        )
        inspection["inspection"]["path"] = self._relative_or_name(path)
        return {"path": self._relative_or_name(path), **inspection}

    def _dict_validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = self._payload_path(
            payload,
            "path",
            self._default_dictionary_path(),
            must_exist="inputs" not in payload,
        )
        dictionary = load_and_normalize(
            self._input_paths(payload, path),
            policy=self._dictionary_policy(payload),
        )
        return {
            "entries": len(dictionary.entries),
            "mappingHash": dictionary.mapping_hash,
            "warnings": list(dictionary.warnings),
        }

    def _dict_read(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        default = self._default_dictionary_path()
        path = (
            self._payload_path(payload, "path", default)
            if "path" in payload
            else default
        )
        if not path.is_file():
            path = default
        self._assert_dictionary_path(path)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise ShieldFontError(
                "Unable to read dictionary CSV",
                code=ErrorCode.DICTIONARY_PARSE,
                exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                stage="dictionary.read",
                details={"file": str(path), "reason": str(error)},
            ) from error
        return {"path": self._relative_or_name(path), "content": content}

    def _dict_default_set(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = self._payload_path(
            payload,
            "path",
            self._default_dictionary_path(),
            must_exist=True,
        )
        self._assert_dictionary_path(path)
        relative = self._relative_or_name(path)
        try:
            temporary = self.default_dictionary_state.with_suffix(".tmp")
            temporary.write_text(relative, encoding="utf-8", newline="")
            temporary.replace(self.default_dictionary_state)
        except OSError as error:
            raise ShieldFontError(
                "Unable to save the default dictionary selection",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="dictionary.default",
                details={
                    "file": str(self.default_dictionary_state),
                    "reason": str(error),
                },
            ) from error
        LOGGER.info("[FIX] Default dictionary selected", extra={"path": relative})
        return {"path": relative}

    def _dict_save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ShieldFontError(
                "Dictionary CSV content must not be empty",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="dictionary.write",
            )
        path = self._payload_path(
            payload,
            "path",
            self._default_dictionary_path(),
        )
        self._assert_dictionary_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8", newline="")
        except OSError as error:
            raise ShieldFontError(
                "Unable to save dictionary CSV",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="dictionary.write",
                details={"file": str(path), "reason": str(error)},
            ) from error
        LOGGER.info("[FIX] Dictionary CSV saved", extra={"path": str(path)})
        return {"path": self._relative_or_name(path), "content": content}

    def _project_read(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = self._project_payload_path(payload, must_exist=True)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise ShieldFontError(
                "Unable to read project YAML",
                code=ErrorCode.CONFIG_INVALID,
                exit_code=ExitCode.INVALID_INPUT,
                stage="project.read",
                details={"file": str(path), "reason": str(error)},
            ) from error
        return {"path": self._relative_or_name(path), "content": content}

    def _project_save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ShieldFontError(
                "Project YAML content must not be empty",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="project.write",
            )
        path = self._project_payload_path(payload)
        try:
            path.write_text(content, encoding="utf-8", newline="")
        except OSError as error:
            raise ShieldFontError(
                "Unable to save project YAML",
                code=ErrorCode.CONFIG_INVALID,
                exit_code=ExitCode.INVALID_INPUT,
                stage="project.write",
                details={"file": str(path), "reason": str(error)},
            ) from error
        LOGGER.info("[FIX] Project YAML saved", extra={"path": str(path)})
        return {"path": self._relative_or_name(path), "content": content}

    @staticmethod
    def _assert_dictionary_path(path: Path) -> None:
        if path.suffix.lower() != ".csv":
            raise ShieldFontError(
                "Dictionary path must use the .csv extension",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="dictionary.path",
            )

    def _dict_normalize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = self._payload_path(
            payload,
            "path",
            self._default_dictionary_path(),
            must_exist="inputs" not in payload,
        )
        dictionary = load_and_normalize(
            self._input_paths(payload, path),
            policy=self._dictionary_policy(payload),
        )
        output_dir = self._payload_path(
            payload,
            "outputDir",
            Path("dist/dictionaries"),
        )
        stem = self._safe_stem(payload.get("stem", path.stem))
        artifacts = write_dictionary_artifacts(
            dictionary,
            output_dir=output_dir,
            stem=stem,
        )
        return {
            "entries": len(dictionary.entries),
            "mappingHash": dictionary.mapping_hash,
            "warnings": list(dictionary.warnings),
            "artifacts": self._artifact_paths(artifacts),
        }

    def _css_build(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config = self._load_config()
        selected_source = self._selected_source_path(payload)
        if selected_source is not None:
            try:
                self._assert_css_source_matches(
                    config.project.output_dir,
                    selected_source,
                )
            except ShieldFontError:
                LOGGER.info(
                    "[FIX] CSS build refreshing stale selected-font artifact",
                    extra={
                        "source": self._relative_or_name(selected_source),
                        "outputDir": str(config.project.output_dir),
                    },
                )
                build_project(
                    self._config_path(),
                    output_dir=config.project.output_dir,
                    source_path=selected_source,
                )
                self._assert_css_source_matches(
                    config.project.output_dir,
                    selected_source,
                )
                LOGGER.info(
                    "[FIX] CSS build refreshed selected-font artifact",
                    extra={
                        "source": self._relative_or_name(selected_source),
                    },
                )
            LOGGER.info(
                "[FIX] CSS build source font verified",
                extra={"path": self._relative_or_name(selected_source)},
            )
        font_path = (
            config.project.output_dir
            / "fonts"
            / output_font_filename(config.font.family, "woff2")
        ).resolve()
        if not font_path.is_file():
            raise ShieldFontError(
                "Generated ShieldFont artifact is unavailable; run build first",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
                details={"font": str(font_path)},
            )
        output_path = self._payload_path(payload, "output", config.css.file)
        asset_base_url = payload.get("assetBaseUrl", config.css.asset_base_url)
        if not isinstance(asset_base_url, str) or not asset_base_url.strip():
            raise ShieldFontError(
                "CSS asset base URL must be a non-empty string",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
            )
        if "\r" in asset_base_url or "\n" in asset_base_url:
            raise ShieldFontError(
                "CSS asset base URL must not contain line breaks",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
            )
        font_display = payload.get("fontDisplay", config.css.font_display)
        if font_display not in {"auto", "block", "swap", "fallback", "optional"}:
            raise ShieldFontError(
                "Unsupported CSS font display value",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
                details={"fontDisplay": font_display},
            )
        embed_font = payload.get("embedFont", config.css.embed_font)
        if not isinstance(embed_font, bool):
            raise ShieldFontError(
                "embedFont must be a boolean",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
            )
        include_ttf_fallback = payload.get("includeTtfFallback", False)
        if not isinstance(include_ttf_fallback, bool):
            raise ShieldFontError(
                "includeTtfFallback must be a boolean",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
            )
        artifacts = build_css(
            CssFace(config.font.shield_face.family, font_path.name),
            options=CssBuildOptions(
                asset_base_url=asset_base_url,
                font_display=font_display,
                font_synthesis=config.css.font_synthesis,
                shield_class=config.css.classes.shield,
                neutral_class=config.css.classes.neutral,
                include_ttf_fallback=include_ttf_fallback,
                embed_font=embed_font,
            ),
            asset_root=font_path.parent,
            output_path=output_path,
        )
        return {"artifacts": {key: str(value) for key, value in artifacts.items()}}

    def _selected_source_path(self, payload: Mapping[str, Any]) -> Path | None:
        if "sourceFont" not in payload:
            return None
        return self._font_payload_path(payload, "sourceFont")

    def _assert_css_source_matches(
        self,
        output_dir: Path,
        source_path: Path,
    ) -> None:
        manifest_path = output_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ShieldFontError(
                "Generated ShieldFont manifest is unavailable; run build first",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
                details={"manifest": str(manifest_path)},
            ) from error
        source = manifest.get("source") if isinstance(manifest, dict) else None
        expected_hash = f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}"
        if (
            not isinstance(source, dict)
            or source.get("path") != source_path.name
            or source.get("sha256") != expected_hash
        ):
            raise ShieldFontError(
                "Generated ShieldFont artifact does not match the selected "
                "source font; run build first",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.css.input",
                details={
                    "manifest": str(manifest_path),
                    "font": self._relative_or_name(source_path),
                },
            )

    def _config_metadata(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        del payload
        config = self._load_config()
        data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        self._redact_config(data)
        data = self._relativize_config(data)
        return {
            "configPath": self._relative_or_name(self._config_path()),
            "schema": data.get("schema", "shieldfont/v1"),
            "parameters": data,
            "defaultDictionary": self._relative_or_name(
                self._default_dictionary_path()
            ),
            "mutableFields": sorted(_MUTABLE_CONFIG_FIELDS),
        }

    def _config_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        updates = payload.get("updates")
        if updates is None and isinstance(payload.get("field"), str):
            updates = _dotted_update(
                str(payload["field"]),
                payload.get("value"),
            )
        if not isinstance(updates, Mapping) or not updates:
            raise ShieldFontError(
                "Config updates must be a non-empty object",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config.update",
            )
        self._validate_config_update(updates)
        config = self._load_config()
        data = config.model_dump(mode="python", by_alias=True, exclude_none=False)
        _deep_merge(data, updates)
        try:
            updated = type(config).model_validate(data)
        except Exception as error:
            raise ShieldFontError(
                "Configuration update failed validation",
                code=ErrorCode.CONFIG_INVALID,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config.update",
            ) from error
        self._config_path().write_text(
            dump_resolved_config(updated),
            encoding="utf-8",
        )
        log_event(
            LOGGER,
            logging.INFO,
            "Web configuration updated",
            stage="web.config.update",
            details={"fields": len(updates)},
        )
        return self._config_metadata({})

    def _test_text(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        text = payload.get("text")
        if not isinstance(text, str) or not text or len(text) > 32_768:
            raise ShieldFontError(
                "Test text must be a non-empty string no longer than 32768 characters",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.test_text.input",
            )
        ruleset_path = self._payload_path(
            payload,
            "ruleset",
            Path("dist/ruleset.json"),
            must_exist=True,
        )
        try:
            import json

            ruleset = json.loads(ruleset_path.read_text(encoding="utf-8"))
            scopes = ruleset["scopes"]
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            raise ShieldFontError(
                "ShieldFont ruleset is unavailable for test text",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.test_text.ruleset",
            ) from error
        scope_id = payload.get("scope")
        scope = next(
            (
                item
                for item in scopes
                if isinstance(item, Mapping)
                and (scope_id is None or item.get("id") == scope_id)
            ),
            None,
        )
        if not isinstance(scope, Mapping):
            raise ShieldFontError(
                "Requested test-text scope is unavailable",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.test_text.scope",
            )
        rules = scope.get("rules", [])
        if not isinstance(rules, list):
            raise ShieldFontError(
                "ShieldFont ruleset contains invalid rules",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.test_text.ruleset",
            )
        shield_text, applied = _encode_test_text(text, rules)
        LOGGER.debug(
            "[FIX] Encoded test text using whole-word mapping",
            extra={"rulesApplied": applied},
        )
        return {"shieldFont": shield_text, "scope": scope.get("id")}

    def _config_path(self) -> Path:
        return self.project_root / "shieldfont.yml"

    def _project_payload_path(
        self,
        payload: Mapping[str, Any],
        *,
        must_exist: bool = False,
    ) -> Path:
        path = self._payload_path(
            payload,
            "path",
            Path("shieldfont.yml"),
            must_exist=must_exist,
        )
        if path.suffix.lower() not in {".yml", ".yaml"}:
            raise ShieldFontError(
                "Project file must use the .yml or .yaml extension",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="project.path",
            )
        return path

    def _load_config(self) -> Any:
        config = load_config(self._config_path())
        paths = [
            config.project.output_dir,
            config.source.path,
            config.css.file,
            *(
                dictionary
                for scope in config.scopes
                for dictionary in scope.dictionaries
            ),
        ]
        for path in paths:
            self._confined_config_path(path)
        return config

    def _source_path(self) -> Path:
        return self._assert_font_directory(
            self._confined_config_path(self._load_config().source.path)
        )

    def _default_dictionary_path(self) -> Path:
        fallback = (self.project_root / "dictionaries/default.csv").resolve()
        try:
            selected = self.default_dictionary_state.read_text(
                encoding="utf-8",
            ).strip()
        except FileNotFoundError:
            return fallback
        except OSError as error:
            LOGGER.warning(
                "[FIX] Default dictionary state could not be read",
                extra={
                    "file": str(self.default_dictionary_state),
                    "reason": str(error),
                },
            )
            return fallback
        if not selected:
            return fallback
        try:
            candidate = self._payload_path({"path": selected}, "path", fallback)
        except ShieldFontError:
            LOGGER.warning(
                "[FIX] Invalid default dictionary state ignored",
                extra={"path": selected},
            )
            return fallback
        return (
            candidate
            if candidate.is_file() and candidate.suffix.lower() == ".csv"
            else fallback
        )

    def _dictionary_policy(self, payload: Mapping[str, Any]) -> Any:
        configured_mode = (
            self._load_config().mapping.mode
            if self._config_path().is_file()
            else "involution"
        )
        return policy_from_options(
            mapping_mode=str(payload.get("mappingMode", configured_mode)),
            duplicate_policy=str(payload.get("duplicatePolicy", "error")),
            target_collision_policy=str(
                payload.get("targetCollisionPolicy", "error")
            ),
            self_map_policy=str(
                payload.get("selfMapPolicy", "drop-with-warning")
            ),
        )

    def _input_paths(
        self,
        payload: Mapping[str, Any],
        default: Path,
        *,
        key: str = "inputs",
    ) -> tuple[Path, ...]:
        values = payload.get(key)
        if values is None:
            return (default,)
        if not isinstance(values, list) or not values:
            raise ShieldFontError(
                f"{key} must be a non-empty array",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.path.validate",
            )
        return tuple(
            self._payload_path(
                {"path": value},
                "path",
                Path("."),
                must_exist=True,
            )
            for value in values
        )

    @staticmethod
    def _safe_stem(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}",
            value,
        ):
            raise ShieldFontError(
                "Artifact stem contains invalid characters",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.path.validate",
            )
        return value

    def _artifact_paths(self, artifacts: Mapping[str, Path]) -> dict[str, str]:
        return {key: str(value) for key, value in artifacts.items()}

    def _relative_or_name(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _redact_config(value: Any, *, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key in list(value):
                if child_key.lower() == "apikey":
                    value[child_key] = "<environment-reference>"
                else:
                    WebActions._redact_config(value[child_key], key=child_key)
        elif isinstance(value, list):
            for item in value:
                WebActions._redact_config(item, key=key)

    def _relativize_config(self, value: Any, *, key: str = "") -> Any:
        if isinstance(value, dict):
            return {
                child_key: self._relativize_config(
                    child_value,
                    key=str(child_key),
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [self._relativize_config(item, key=key) for item in value]
        if key in {"path", "file", "outputDir", "dictionaries"} and isinstance(
            value,
            str,
        ):
            try:
                relative = Path(value).resolve().relative_to(self.project_root)
            except ValueError:
                return value
            return relative.as_posix() if relative.parts else "."
        return value

    def _validate_config_update(
        self,
        updates: Mapping[str, Any],
        *,
        prefix: str = "",
    ) -> None:
        forbidden = {"apikey", "api_key", "command", "shell", "exec"}
        for key, value in updates.items():
            name = str(key)
            if name.lower() in forbidden:
                raise ShieldFontError(
                    "Provider credentials and commands cannot be changed "
                    "through the web API",
                    code=ErrorCode.INVALID_INPUT,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="web.config.update",
                )
            field = f"{prefix}.{name}" if prefix else name
            if isinstance(value, Mapping) and field in _MUTABLE_CONFIG_FIELDS:
                continue
            if isinstance(value, Mapping):
                self._validate_config_update(
                    value,
                    prefix=field,
                )
            else:
                if field not in _MUTABLE_CONFIG_FIELDS:
                    raise ShieldFontError(
                        "Configuration field is not editable through the web API",
                        code=ErrorCode.INVALID_INPUT,
                        exit_code=ExitCode.INVALID_INPUT,
                        stage="web.config.update",
                    )
            if not isinstance(value, Mapping) and name in {
                "path",
                "file",
                "outputDir",
                "dictionaries",
            }:
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if not isinstance(item, str):
                        continue
                    candidate = self._payload_path({"path": item}, "path", Path("."))
                    if field == "source.path":
                        self._assert_font_directory(candidate)

    def _confined_config_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError as error:
            raise ShieldFontError(
                "Configuration path escapes the project root",
                code=ErrorCode.CONFIG_INVALID,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config.path",
            ) from error
        current = self.project_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ShieldFontError(
                    "Configuration paths may not traverse symlinks",
                    code=ErrorCode.CONFIG_INVALID,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="web.config.path",
                )
        return resolved

    def _font_payload_path(self, payload: Mapping[str, Any], key: str) -> Path:
        path = self._payload_path(payload, key, Path("."), must_exist=True)
        return self._assert_font_directory(path)

    def _assert_font_directory(self, path: Path) -> Path:
        try:
            relative = path.relative_to(self.fonts_root)
        except ValueError as error:
            raise ShieldFontError(
                "Font path must be inside the configured fonts directory",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.path",
            ) from error
        if not relative.parts:
            raise ShieldFontError(
                "Font path must be inside the configured fonts directory",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.path",
            )
        return path

    def _payload_path(
        self,
        payload: Mapping[str, Any],
        key: str,
        default: Path,
        *,
        must_exist: bool = False,
    ) -> Path:
        provided = key in payload
        value = payload.get(key, str(default))
        if not isinstance(value, str) or not value:
            raise ShieldFontError(
                "Web action path must be a non-empty string",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.action.path",
            )
        candidate = Path(value)
        if (provided and candidate.is_absolute()) or ".." in candidate.parts:
            raise ShieldFontError(
                "Web action path escapes the project root",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.action.path",
            )
        resolved = (
            candidate.resolve()
            if not provided and candidate.is_absolute()
            else (self.project_root / candidate).resolve()
        )
        try:
            resolved.relative_to(self.project_root)
        except ValueError as error:
            raise ShieldFontError(
                "Web action path escapes the project root",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.action.path",
            ) from error
        relative = resolved.relative_to(self.project_root)
        current = self.project_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ShieldFontError(
                    "Web action paths may not traverse symlinks",
                    code=ErrorCode.INVALID_INPUT,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="web.action.path",
                )
        if must_exist and (not resolved.exists() or not resolved.is_file()):
            raise ShieldFontError(
                "Selected project file does not exist",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.action.path",
            )
        return resolved


_MUTABLE_CONFIG_FIELDS = frozenset(
    {
        "project.id",
        "project.version",
        "project.outputDir",
        "source.path",
        "source.instance.axes",
        "font.family",
        "font.description",
        "layout.maxEstimatedSubtableBytes",
        "mapping.mode",
        "mapping.duplicatePolicy",
        "mapping.targetCollisionPolicy",
        "mapping.selfMapPolicy",
        "css.file",
        "css.assetBaseUrl",
        "css.fontDisplay",
        "css.classes.shield",
        "css.classes.neutral",
    }
)


def _deep_merge(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[str(key)] = value


def _dotted_update(field: str, value: Any) -> dict[str, Any]:
    parts = [part for part in field.split(".") if part]
    if not parts:
        return {}
    result: Any = value
    for part in reversed(parts):
        result = {part: result}
    return cast(dict[str, Any], result)
