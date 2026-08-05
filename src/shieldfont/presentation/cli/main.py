"""Console-script entrypoint."""

from __future__ import annotations

import logging

import typer

from shieldfont.domain.errors import ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event
from shieldfont.presentation.cli.app import app

LOGGER = logging.getLogger("shieldfont.cli")


def main() -> None:
    """Run the CLI and translate domain failures into stable exit codes."""

    try:
        app()
    except ShieldFontError as error:
        log_event(
            LOGGER,
            logging.ERROR,
            str(error),
            code=error.code.value,
            stage=error.stage,
            details=error.details,
            exc_info=True,
        )
        raise typer.Exit(code=int(error.exit_code)) from error
    except KeyboardInterrupt as error:
        log_event(
            LOGGER,
            logging.WARNING,
            "Command interrupted",
            code="SF-INTERRUPTED",
            stage="cli.run",
        )
        raise typer.Exit(code=int(ExitCode.GENERIC_FAILURE)) from error


if __name__ == "__main__":
    main()
