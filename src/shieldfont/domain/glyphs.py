"""Framework-independent glyph builder contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GlyphBuildResult:
    """Metrics and identity of one generated composite glyph."""

    glyph_name: str
    source: str
    advance_width: int
    lsb: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    component_count: int


class TrueTypeGlyphBuilder(Protocol):
    """Port for deterministic composite TrueType glyph construction."""

    def supports(self) -> bool:
        """Return whether the current font has the required TrueType tables."""

    def create_word_glyph(self, source: str, glyph_name: str) -> GlyphBuildResult:
        """Create one composite glyph from source character components."""

    def finalize(self) -> None:
        """Reconcile glyph and horizontal metric table counts."""
