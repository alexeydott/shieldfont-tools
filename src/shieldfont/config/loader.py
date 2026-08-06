"""Deterministic YAML loading, validation, and path resolution."""

from __future__ import annotations

import logging
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, SecretStr, ValidationError

from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.config")
_ENV_PREFIX = "${ENV:"


def _model_type(annotation: Any) -> type[BaseModel] | None:
    origin = get_origin(annotation)
    if origin in {Union, types.UnionType}:
        for item in get_args(annotation):
            model = _model_type(item)
            if model is not None:
                return model
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _list_model_type(annotation: Any) -> type[BaseModel] | None:
    if get_origin(annotation) is not list:
        return None
    args = get_args(annotation)
    return _model_type(args[0]) if args else None


def _prune_unknown(
    data: Mapping[str, Any],
    model_type: type[BaseModel],
    *,
    path: str = "",
) -> tuple[dict[str, Any], list[str]]:
    fields_by_key = {
        field.alias or name: field for name, field in model_type.model_fields.items()
    }
    output: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in data.items():
        field = fields_by_key.get(key)
        field_path = f"{path}.{key}" if path else key
        if field is None:
            unknown.append(field_path)
            continue
        nested_model = _model_type(field.annotation)
        list_model = _list_model_type(field.annotation)
        if nested_model is not None and isinstance(value, Mapping):
            output[key], nested_unknown = _prune_unknown(
                value, nested_model, path=field_path
            )
            unknown.extend(nested_unknown)
        elif list_model is not None and isinstance(value, list):
            items: list[Any] = []
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    pruned, nested_unknown = _prune_unknown(
                        item,
                        list_model,
                        path=f"{field_path}[{index}]",
                    )
                    items.append(pruned)
                    unknown.extend(nested_unknown)
                else:
                    items.append(item)
            output[key] = items
        else:
            output[key] = value
    return output, unknown


def _validate_env_references(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_env_references(item, path=(*path, str(key)))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_env_references(item, path=(*path, str(index)))
        return
    if not isinstance(value, str) or _ENV_PREFIX not in value:
        return
    dotted_path = ".".join(path)
    raise ShieldFontError(
        "Environment references are not supported in project configuration",
        code=ErrorCode.CONFIG_ENV_REFERENCE,
        exit_code=ExitCode.INVALID_INPUT,
        stage="config.environment",
        details={"field": dotted_path},
    )


def _resolve_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else (base_dir / path).resolve()


def resolve_config_paths(config: ShieldFontConfig, base_dir: Path) -> ShieldFontConfig:
    """Return a deep copy with every filesystem path resolved from the config."""

    resolved = config.model_copy(deep=True)
    resolved.project.output_dir = _resolve_path(resolved.project.output_dir, base_dir)
    resolved.source.path = _resolve_path(resolved.source.path, base_dir)
    resolved.css.file = _resolve_path(resolved.css.file, base_dir)
    for scope in resolved.scopes:
        scope.dictionaries = [
            _resolve_path(dictionary, base_dir) for dictionary in scope.dictionaries
        ]
    resolved.protection.inventory = [
        _resolve_path(path, base_dir) for path in resolved.protection.inventory
    ]
    return resolved


def load_config(path: Path, *, strict: bool = True) -> ShieldFontConfig:
    """Load and resolve a ``shieldfont/v1`` YAML file."""

    config_path = path.resolve()
    log_event(
        LOGGER,
        logging.DEBUG,
        "Loading ShieldFont configuration",
        code="SF-CONFIG-LOAD",
        stage="config.load",
        details={"path": str(config_path), "strict": strict},
    )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ShieldFontError(
            "Unable to read ShieldFont configuration",
            code=ErrorCode.CONFIG_INVALID,
            exit_code=ExitCode.INVALID_INPUT,
            stage="config.load",
            details={"path": str(config_path), "reason": str(error)},
        ) from error
    if not isinstance(raw, Mapping):
        raise ShieldFontError(
            "ShieldFont configuration must be a YAML mapping",
            code=ErrorCode.CONFIG_INVALID,
            exit_code=ExitCode.INVALID_INPUT,
            stage="config.validate",
            details={"path": str(config_path)},
        )

    _validate_env_references(raw)
    payload: Mapping[str, Any] = raw
    if not strict:
        payload, unknown = _prune_unknown(raw, ShieldFontConfig)
        for field_path in unknown:
            log_event(
                LOGGER,
                logging.WARNING,
                "Ignoring unknown configuration field in non-strict mode",
                code="SF-CONFIG-UNKNOWN-FIELD",
                stage="config.validate",
                details={"field": field_path},
            )
    try:
        config = ShieldFontConfig.model_validate(payload)
    except ValidationError as error:
        raise ShieldFontError(
            "ShieldFont configuration validation failed",
            code=ErrorCode.CONFIG_INVALID,
            exit_code=ExitCode.INVALID_INPUT,
            stage="config.validate",
            details={"errors": error.errors(include_url=False)},
        ) from error

    resolved = resolve_config_paths(config, config_path.parent)
    log_event(
        LOGGER,
        logging.INFO,
        "ShieldFont configuration loaded",
        code="SF-CONFIG-LOADED",
        stage="config.load",
        details={"path": str(config_path), "scopes": len(resolved.scopes)},
    )
    return resolved


def dump_resolved_config(
    config: ShieldFontConfig,
    *,
    reveal_secrets: bool = False,
) -> str:
    """Serialize deterministically, redacting private inputs by default."""

    data = config.model_dump(mode="python", by_alias=True, exclude_none=True)

    def serialize_value(value: Any) -> Any:
        if isinstance(value, SecretStr):
            return value.get_secret_value() if reveal_secrets else "<redacted>"
        if isinstance(value, Mapping):
            return {key: serialize_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [serialize_value(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value

    return yaml.safe_dump(
        serialize_value(data),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    )
