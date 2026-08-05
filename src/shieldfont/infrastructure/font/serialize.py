"""TrueType and WOFF2 serialization adapter."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError


def serialize_true_type(font: TTFont, output_path: Path) -> Path:
    """Serialize a glyf font as TTF or WOFF2 with deterministic flavor selection."""

    destination = output_path.resolve()
    suffix = destination.suffix.lower()
    if suffix not in {".ttf", ".woff2"}:
        raise ShieldFontError(
            "Only TTF and WOFF2 outputs are supported",
            code=ErrorCode.FONT_UNSUPPORTED,
            exit_code=ExitCode.UNSUPPORTED_FONT,
            stage="font.serialize",
            details={"path": str(destination)},
        )
    if "glyf" not in font:
        raise ShieldFontError(
            "Only TrueType glyf fonts can be serialized",
            code=ErrorCode.FONT_UNSUPPORTED,
            exit_code=ExitCode.UNSUPPORTED_FONT,
            stage="font.serialize",
            details={"path": str(destination)},
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    font.flavor = "woff2" if suffix == ".woff2" else None
    try:
        font.save(destination)
    except (OSError, TTLibError, ValueError) as error:
        raise ShieldFontError(
            "Unable to serialize TrueType font",
            code=ErrorCode.FONT_SERIALIZATION,
            exit_code=ExitCode.FONT_SERIALIZATION_ERROR,
            stage="font.serialize",
            details={"path": str(destination), "reason": str(error)},
        ) from error
    return destination
