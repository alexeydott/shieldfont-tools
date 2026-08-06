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

LOGGER = logging.getLogger("shieldfont.generate")

generate_app = typer.Typer(
    name="shieldfont-generate",
    help="Generate ShieldFont artifacts from a profile and command-line overrides.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
)


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
  shieldfont-generate run shieldfont.yml --source .fonts\\segoepr.ttf `
    --postfix _ru --output-dir build\\ru --json
  shieldfont-generate run shieldfont.yml --source .fonts\\segoepr.ttf `
    --family MyShieldFont --output-dir build\\custom
  shieldfont-generate run shieldfont.yml --source .fonts\\segoepr.ttf `
    --dictionary dictionaries\\default.csv --font-display swap
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
