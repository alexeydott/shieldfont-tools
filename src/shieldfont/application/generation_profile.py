"""Profile loading and typed command-line override resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shieldfont.config.loader import load_config
from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font_naming import shield_family_name
from shieldfont.infrastructure.font.inspect import inspect_font_for_init
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.generation_profile")


def _resolved_path(value: Path, profile_path: Path) -> Path:
    return value if value.is_absolute() else (profile_path.parent / value).resolve()


def resolve_generation_profile(
    profile_path: Path,
    *,
    output_dir: Path | None = None,
    source_path: Path | None = None,
    dictionary_path: Path | None = None,
    family: str | None = None,
    postfix: str | None = None,
    project_id: str | None = None,
    project_version: str | None = None,
    font_display: str | None = None,
    embed_font: bool | None = None,
    protection_profile: str | None = None,
    mapping_contract: str | None = None,
    mapping_seed: str | None = None,
    document_nonce: str | None = None,
    tenant_id: str | None = None,
    inventory_paths: list[Path] | None = None,
    reserve_aliases: int | None = None,
    scan_public_artifacts: bool | None = None,
    gsub_optimization: str | None = None,
    strict: bool = True,
) -> ShieldFontConfig:
    """Load a profile and apply explicit command-line overrides."""

    resolved_profile = profile_path.resolve()
    config = load_config(resolved_profile, strict=strict)
    payload: dict[str, Any] = config.model_dump(mode="python", by_alias=False)

    if output_dir is not None:
        payload["project"]["output_dir"] = _resolved_path(
            output_dir, resolved_profile
        )
    if source_path is not None:
        payload["source"]["path"] = _resolved_path(source_path, resolved_profile)
    if dictionary_path is not None:
        payload["scopes"] = [
            {
                **scope,
                "dictionaries": [
                    _resolved_path(dictionary_path, resolved_profile)
                ],
            }
            for scope in payload["scopes"]
        ]
    if family is not None and postfix is not None:
        raise ShieldFontError(
            "Use either --family or --postfix, not both",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="config.override",
        )
    if family is not None:
        payload["font"]["family"] = family
    if postfix is not None:
        normalized_postfix = postfix.strip()
        if not normalized_postfix:
            raise ShieldFontError(
                "Font family postfix must not be empty",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="config.override",
            )
        source_summary = inspect_font_for_init(Path(payload["source"]["path"]))
        generated_family = shield_family_name(
            source_summary.family,
            normalized_postfix,
        )
        payload["font"]["family"] = generated_family
        log_event(
            LOGGER,
            logging.DEBUG,
            "Applied source-family postfix override",
            code="SF-CONFIG-FAMILY-POSTFIX",
            stage="config.override",
            details={
                "source_family": source_summary.family,
                "postfix": normalized_postfix,
                "generated_family": generated_family,
            },
        )
    if project_id is not None:
        payload["project"]["id"] = project_id
    if project_version is not None:
        payload["project"]["version"] = project_version
    if font_display is not None:
        payload["css"]["font_display"] = font_display
    if embed_font is not None:
        payload["css"]["embed_font"] = embed_font
    if protection_profile is not None:
        payload["protection"]["profile"] = protection_profile
        if protection_profile == "document-bound" and mapping_contract is None:
            payload["protection"]["mapping_contract"] = "shieldfont.mapping.v2"
        if protection_profile == "document-bound" and scan_public_artifacts is None:
            payload["protection"]["scan_public_artifacts"] = True
    if mapping_contract is not None:
        payload["protection"]["mapping_contract"] = mapping_contract
    if mapping_seed is not None:
        payload["protection"]["seed"] = mapping_seed
    if document_nonce is not None:
        payload["protection"]["document_nonce"] = document_nonce
    if tenant_id is not None:
        payload["protection"]["tenant_id"] = tenant_id
    if inventory_paths is not None:
        payload["protection"]["inventory"] = [
            _resolved_path(path, resolved_profile) for path in inventory_paths
        ]
    if reserve_aliases is not None:
        payload["protection"]["reserve_aliases"] = reserve_aliases
    if scan_public_artifacts is not None:
        payload["protection"]["scan_public_artifacts"] = scan_public_artifacts
    if gsub_optimization is not None:
        payload["layout"]["gsub_optimization"] = gsub_optimization

    try:
        return ShieldFontConfig.model_validate(payload)
    except ValidationError as error:
        raise ShieldFontError(
            "Generation profile overrides are invalid",
            code=ErrorCode.CONFIG_INVALID,
            exit_code=ExitCode.INVALID_INPUT,
            stage="config.override",
            details={
                "profile": str(resolved_profile),
                "errors": error.errors(include_url=False),
            },
        ) from error
