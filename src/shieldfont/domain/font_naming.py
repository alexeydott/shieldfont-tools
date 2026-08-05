"""Derived naming rules for generated ShieldFont faces."""

from __future__ import annotations

import re

OUTPUT_FONT_SUBFAMILY = "Regular"
OUTPUT_TYPOGRAPHIC_FAMILY = "ShieldFont"
DEFAULT_FONT_POSTFIX = "_shld"


def normalized_family_stem(family: str) -> str:
    """Return the compact family stem used in generated face names."""

    stem = re.sub(r"[^A-Za-z0-9]", "", family)
    return stem or "ShieldFont"


def shield_family_name(
    source_family: str,
    postfix: str = DEFAULT_FONT_POSTFIX,
) -> str:
    """Build the generated family name from the source family and postfix."""

    return f"{normalized_family_stem(source_family)}{postfix}"


def neutral_family_name(source_family: str) -> str:
    """Build the readable family name for the unmodified source face."""

    return f"{normalized_family_stem(source_family)} Text"


def output_font_filename(family: str, extension: str) -> str:
    """Return the deterministic filename for one generated font face."""

    suffix = extension.lstrip(".").lower()
    if suffix not in {"ttf", "woff2"}:
        raise ValueError(f"Unsupported font extension: {extension}")
    return f"{family}-{OUTPUT_FONT_SUBFAMILY}.{suffix}"


def output_post_script_name(
    family: str,
    subfamily: str = OUTPUT_FONT_SUBFAMILY,
) -> str:
    """Build a valid PostScript name from the generated family metadata."""

    family_part = re.sub(r"[^A-Za-z0-9]", "", family)
    subfamily_part = re.sub(r"[^A-Za-z0-9]", "", subfamily)
    return f"{family_part}-{subfamily_part}"[:63]
