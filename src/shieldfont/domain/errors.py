"""Typed errors and stable process exit codes."""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum, StrEnum
from typing import Any


class ExitCode(IntEnum):
    """Stable CLI exit codes defined by the project specification."""

    SUCCESS = 0
    GENERIC_FAILURE = 1
    INVALID_INPUT = 2
    SOURCE_FONT_ERROR = 10
    UNSUPPORTED_FONT = 11
    DICTIONARY_PARSE_ERROR = 20
    DICTIONARY_CONFLICT = 21
    FEATURE_GENERATION_ERROR = 30
    GSUB_COMPILE_ERROR = 31
    FONT_SERIALIZATION_ERROR = 40
    SHAPING_VERIFICATION_ERROR = 50
    CODEC_VERIFICATION_ERROR = 51
    BROWSER_VERIFICATION_ERROR = 52
    TRANSLATION_PROVIDER_ERROR = 60
    LLM_VALIDATION_ERROR = 61
    LICENSING_POLICY_ERROR = 70


class ErrorCode(StrEnum):
    """Machine-readable error identifiers used by structured logs."""

    GENERIC = "SF-GENERIC"
    INVALID_INPUT = "SF-INVALID-INPUT"


class ShieldFontError(Exception):
    """Base error carrying stable machine-readable diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.GENERIC,
        exit_code: ExitCode = ExitCode.GENERIC_FAILURE,
        stage: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.stage = stage
        self.details = dict(details or {})
