"""Typer application and global command options."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from shieldfont import __version__
from shieldfont.infrastructure.logging import (
    LogFormat,
    configure_logging,
    log_event,
    resolve_log_settings,
)

app = typer.Typer(
    name="shieldfont",
    help="Build and verify multilingual TrueType ShieldFont assets.",
    no_args_is_help=True,
    add_completion=False,
)

LOGGER = logging.getLogger("shieldfont.cli")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


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
