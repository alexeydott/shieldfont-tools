"""Configurable text and JSON logging for CLI and library boundaries."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class LogFormat(StrEnum):
    """Supported log renderers."""

    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class LogSettings:
    """Resolved logging settings."""

    level: int
    format: LogFormat
    enabled: bool = True


class JsonEventFormatter(logging.Formatter):
    """Render a logging record as a stable JSON event."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "code": getattr(record, "code", None),
            "stage": getattr(record, "stage", None),
            "message": record.getMessage(),
        }
        details = getattr(record, "details", None)
        if details:
            event["details"] = details
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        return json.dumps(event, ensure_ascii=False, sort_keys=True)


class TextEventFormatter(logging.Formatter):
    """Render a concise human-readable event."""

    def format(self, record: logging.LogRecord) -> str:
        code = getattr(record, "code", None)
        stage = getattr(record, "stage", None)
        context = " ".join(part for part in (code, stage) if part)
        prefix = f"[{record.levelname}]"
        if context:
            prefix = f"{prefix} [{context}]"
        return f"{prefix} {record.getMessage()}"


def resolve_log_settings(
    *,
    log_format: LogFormat = LogFormat.TEXT,
    quiet: bool = False,
    verbose: bool = False,
    trace: bool = False,
) -> LogSettings:
    """Resolve CLI flags and ``LOG_LEVEL`` into deterministic settings."""

    if quiet:
        return LogSettings(level=logging.CRITICAL + 1, format=log_format, enabled=False)
    if trace:
        return LogSettings(level=logging.DEBUG, format=log_format)
    if verbose:
        return LogSettings(level=logging.DEBUG, format=log_format)

    environment_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(environment_level, logging.INFO)
    return LogSettings(level=level, format=log_format)


def configure_logging(settings: LogSettings) -> None:
    """Configure the process root logger from resolved settings."""

    handler = logging.StreamHandler()
    formatter: logging.Formatter
    if settings.format is LogFormat.JSON:
        formatter = JsonEventFormatter()
    else:
        formatter = TextEventFormatter()
    handler.setFormatter(formatter)

    logging.basicConfig(
        level=settings.level,
        handlers=[handler],
        force=True,
    )
    if not settings.enabled:
        logging.disable(logging.CRITICAL)
    else:
        logging.disable(logging.NOTSET)


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    code: str | None = None,
    stage: str | None = None,
    details: dict[str, Any] | None = None,
    exc_info: bool = False,
) -> None:
    """Log a structured event without coupling callers to formatter internals."""

    logger.log(
        level,
        message,
        extra={"code": code, "stage": stage, "details": details or {}},
        exc_info=exc_info,
    )
