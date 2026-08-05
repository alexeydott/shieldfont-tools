"""Minimal font inspection adapter required by project initialization."""

from __future__ import annotations

import logging
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font import FontSummary
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.font.inspect")


def _name(font: TTFont, name_id: int, fallback: str) -> str:
    value = font["name"].getDebugName(name_id) if "name" in font else None
    return value or fallback


def inspect_font_for_init(path: Path) -> FontSummary:
    """Read the metadata needed to seed ``shieldfont.yml``."""

    font_path = path.resolve()
    log_event(
        LOGGER,
        logging.DEBUG,
        "Inspecting source font for initialization",
        code="SF-INIT-FONT-INSPECT",
        stage="init.inspect",
        details={"path": str(font_path)},
    )
    try:
        font = TTFont(font_path, lazy=False)
    except (OSError, TTLibError) as error:
        raise ShieldFontError(
            "Unable to inspect source font",
            code=ErrorCode.INIT_FONT_INVALID,
            exit_code=ExitCode.SOURCE_FONT_ERROR,
            stage="init.inspect",
            details={"path": str(font_path), "reason": str(error)},
        ) from error
    try:
        axes = {
            axis.axisTag: float(axis.defaultValue)
            for axis in getattr(font.get("fvar"), "axes", [])
        }
        weight = int(getattr(font.get("OS/2"), "usWeightClass", 400))
        italic = bool(getattr(font.get("head"), "macStyle", 0) & 0b10)
        return FontSummary(
            family=_name(font, 1, font_path.stem),
            subfamily=_name(font, 2, "Regular"),
            weight=weight,
            style="italic" if italic else "normal",
            has_glyf="glyf" in font,
            variable="fvar" in font,
            axes=axes,
        )
    finally:
        font.close()
