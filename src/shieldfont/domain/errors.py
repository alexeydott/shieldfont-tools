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
    LLM_VALIDATION_ERROR = 61
    LICENSING_POLICY_ERROR = 70


class ErrorCode(StrEnum):
    """Machine-readable error identifiers used by structured logs."""

    GENERIC = "SF-GENERIC"
    INVALID_INPUT = "SF-INVALID-INPUT"
    CONFIG_INVALID = "SF-CONFIG-INVALID"
    CONFIG_ENV_REFERENCE = "SF-CONFIG-ENV-REFERENCE"
    INIT_EXISTS = "SF-INIT-EXISTS"
    INIT_FONT_INVALID = "SF-INIT-FONT-INVALID"
    FONT_INSPECT_INVALID = "SF-FONT-INSPECT-INVALID"
    FONT_UNSUPPORTED = "SF-FONT-UNSUPPORTED"
    FONT_NORMALIZATION = "SF-FONT-NORMALIZATION"
    FONT_LICENSE = "SF-FONT-LICENSE"
    FONT_METADATA = "SF-FONT-METADATA"
    FONT_SERIALIZATION = "SF-FONT-SERIALIZATION"
    FEATURE_GENERATION_ERROR = "SF-FEATURE-GENERATION"
    GSUB_COMPILE_ERROR = "SF-GSUB-COMPILE"
    SHAPING_VERIFICATION_ERROR = "SF-SHAPING-VERIFICATION"
    CODEC_VERIFICATION_ERROR = "SF-CODEC-VERIFICATION"
    DICTIONARY_PARSE = "SF-DICT-PARSE"
    DICTIONARY_SOURCE_COLLISION = "SF-DICT-SOURCE-COLLISION"
    DICTIONARY_TARGET_COLLISION = "SF-DICT-TARGET-COLLISION"
    DICTIONARY_INVOLUTION = "SF-DICT-INVOLUTION"
    LLM_VALIDATION = "SF-LLM-VALIDATION"
    LLM_PROVIDER = "SF-LLM-PROVIDER"


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
