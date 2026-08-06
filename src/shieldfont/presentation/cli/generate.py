"""Standalone profile-driven font generation CLI."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from shieldfont.application.build import build_project
from shieldfont.application.generation_profile import resolve_generation_profile
from shieldfont.infrastructure.logging import (
    LogFormat,
    configure_logging,
    log_event,
    resolve_log_settings,
)
from shieldfont.presentation.cli.app import serve_command

LOGGER = logging.getLogger("shieldfont.generate")

generate_app = typer.Typer(
    name="shieldfont-generate",
    help=r"""Generate ShieldFont artifacts from a profile and command-line overrides.

Examples:

  .\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf

  .\build\shieldfont-generate.exe serve --port 8765
""",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    context_settings={"terminal_width": 120},
)
generate_app.command("serve")(serve_command)


@generate_app.callback()
def configure_generate_cli(
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
) -> None:
    """Configure diagnostics before profile generation."""

    settings = resolve_log_settings(
        log_format=log_format,
        quiet=quiet,
        verbose=verbose,
        trace=trace,
    )
    configure_logging(settings)


@generate_app.command("run")
def generate_command(
    profile_path: Annotated[
        Path,
        typer.Argument(help="YAML generation profile."),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Override the profile output directory."),
    ] = None,
    source_path: Annotated[
        Path | None,
        typer.Option("--source", help="Override the source font path."),
    ] = None,
    dictionary_path: Annotated[
        Path | None,
        typer.Option(
            "--dictionary",
            help="Use one dictionary for every profile scope.",
        ),
    ] = None,
    family: Annotated[
        str | None,
        typer.Option("--family", help="Override the generated font family."),
    ] = None,
    postfix: Annotated[
        str | None,
        typer.Option(
            "--postfix",
            help=(
                "Append this suffix to the normalized original source-family "
                "name."
            ),
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Override the project identifier."),
    ] = None,
    project_version: Annotated[
        str | None,
        typer.Option("--project-version", help="Override the project version."),
    ] = None,
    font_display: Annotated[
        str | None,
        typer.Option("--font-display", help="Override CSS font-display."),
    ] = None,
    embed_font: Annotated[
        bool | None,
        typer.Option(
            "--embed-font/--no-embed-font",
            help="Override CSS font embedding.",
        ),
    ] = None,
    protection_profile: Annotated[
        str | None,
        typer.Option(
            "--protection-profile",
            help="Override compatibility or document-bound profile behavior.",
        ),
    ] = None,
    mapping_contract: Annotated[
        str | None,
        typer.Option(
            "--mapping-contract",
            help="Override shieldfont.mapping.v1 or shieldfont.mapping.v2.",
        ),
    ] = None,
    mapping_seed: Annotated[
        str | None,
        typer.Option(
            "--mapping-seed",
            help="Private deterministic alias-selection seed for mapping v2.",
        ),
    ] = None,
    document_nonce: Annotated[
        str | None,
        typer.Option(
            "--document-nonce",
            help="Private document nonce; public metadata receives only a digest.",
        ),
    ] = None,
    tenant_id: Annotated[
        str | None,
        typer.Option(
            "--tenant-id",
            help="Private cache-isolation input; public metadata receives a digest.",
        ),
    ] = None,
    inventory: Annotated[
        list[Path] | None,
        typer.Option(
            "--inventory",
            help="Document inventory input; repeat for multiple files.",
        ),
    ] = None,
    reserve_aliases: Annotated[
        int | None,
        typer.Option(
            "--reserve-aliases",
            min=0,
            help="Retain deterministic future-coverage entries.",
        ),
    ] = None,
    scan_public_artifacts: Annotated[
        bool | None,
        typer.Option(
            "--scan-public-artifacts/--no-scan-public-artifacts",
            help="Override the pre-publication privacy metadata scan.",
        ),
    ] = None,
    gsub_optimization: Annotated[
        str | None,
        typer.Option(
            "--gsub-optimization",
            help="Override auto, format2, or deterministic format3 behavior.",
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict/--non-strict",
            help="Validate unknown profile fields strictly.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a machine-readable result."),
    ] = False,
) -> None:
    """Generate and atomically publish artifacts from a profile.

Examples:

  .\\build\\shieldfont-generate.exe run shieldfont.yml --source .fonts\\segoepr.ttf

  .\\build\\shieldfont-generate.exe run shieldfont.yml --postfix _ru

  .\\build\\shieldfont-generate.exe run shieldfont.yml --family MyShieldFont

  .\\build\\shieldfont-generate.exe run shieldfont.yml --dictionary default.csv

  .\\build\\shieldfont-generate.exe serve --port 8765
"""

    log_event(
        LOGGER,
        logging.DEBUG,
        "Starting profile-driven generation",
        code="SF-GENERATE-START",
        stage="generate.start",
        details={"profile": str(profile_path.resolve())},
    )
    config = resolve_generation_profile(
        profile_path,
        output_dir=output_dir,
        source_path=source_path,
        dictionary_path=dictionary_path,
        family=family,
        postfix=postfix,
        project_id=project_id,
        project_version=project_version,
        font_display=font_display,
        embed_font=embed_font,
        protection_profile=protection_profile,
        mapping_contract=mapping_contract,
        mapping_seed=mapping_seed,
        document_nonce=document_nonce,
        tenant_id=tenant_id,
        inventory_paths=inventory,
        reserve_aliases=reserve_aliases,
        scan_public_artifacts=scan_public_artifacts,
        gsub_optimization=gsub_optimization,
        strict=strict,
    )
    output = build_project(profile_path, config_override=config)
    log_event(
        LOGGER,
        logging.INFO,
        "Profile-driven generation completed",
        code="SF-GENERATE-COMPLETED",
        stage="generate.complete",
        details={"profile": str(profile_path.resolve()), "output": str(output)},
    )
    if json_output:
        typer.echo(
            json.dumps(
                {"profile": str(profile_path.resolve()), "output": str(output)},
                sort_keys=True,
            )
        )
    else:
        typer.echo(output)
