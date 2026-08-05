"""Application ports for font inspection and diagnostic unpacking."""

from shieldfont.infrastructure.font.inventory import inspect_font, unpack_font
from shieldfont.infrastructure.font.normalize import normalize_font

__all__ = ["inspect_font", "normalize_font", "unpack_font"]
