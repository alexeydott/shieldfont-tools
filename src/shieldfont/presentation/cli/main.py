"""Console-script entrypoint."""

from __future__ import annotations

import logging

from shieldfont.domain.errors import ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event
from shieldfont.presentation.cli.app import app

LOGGER = logging.getLogger("shieldfont.cli")


def main() -> None:
    """Run the CLI and map domain failures into stable exit codes."""

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
        )
        raise SystemExit(int(error.exit_code)) from None
    except KeyboardInterrupt:
        log_event(
            LOGGER,
            logging.WARNING,
            "Command interrupted",
            code="SF-INTERRUPTED",
            stage="cli.run",
        )
        raise SystemExit(int(ExitCode.GENERIC_FAILURE)) from None


if __name__ == "__main__":
    main()
