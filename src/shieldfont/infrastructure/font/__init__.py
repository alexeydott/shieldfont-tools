"""fontTools-backed infrastructure adapters."""

from shieldfont.infrastructure.font.compile import compile_feature_source
from shieldfont.infrastructure.font.glyf_builder import (
    GlyfCompositeBuilder,
    opaque_glyph_name,
)
from shieldfont.infrastructure.font.inspect import inspect_font_for_init
from shieldfont.infrastructure.font.inventory import inspect_font, unpack_font
from shieldfont.infrastructure.font.normalize import normalize_font
from shieldfont.infrastructure.font.serialize import serialize_true_type

__all__ = [
    "GlyfCompositeBuilder",
    "compile_feature_source",
    "inspect_font_for_init",
    "inspect_font",
    "normalize_font",
    "opaque_glyph_name",
    "serialize_true_type",
    "unpack_font",
]
