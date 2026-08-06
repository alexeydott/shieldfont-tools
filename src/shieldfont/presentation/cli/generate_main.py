"""Standalone profile-generation console-script entrypoint."""

from __future__ import annotations

import logging

from shieldfont.domain.errors import ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event
from shieldfont.presentation.cli.generate import generate_app

LOGGER = logging.getLogger("shieldfont.generate")


def main() -> None:
    """Run profile generation and map domain failures to stable exit codes."""

    try:
        generate_app()
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
