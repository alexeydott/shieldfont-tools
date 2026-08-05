"""Deterministic composite glyph builder for TrueType ``glyf`` fonts."""

from __future__ import annotations

import hashlib
import logging

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from fontTools.ttLib.tables._g_l_y_f import (  # type: ignore[import-untyped]
    Glyph,
    GlyphComponent,
)

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.glyphs import GlyphBuildResult

LOGGER = logging.getLogger(__name__)


def opaque_glyph_name(scope_id: str, source: str, salt: str) -> str:
    """Derive a glyph name that does not expose plaintext source text."""

    digest = hashlib.sha256(
        f"{salt}\0{scope_id}\0{source}".encode()
    ).hexdigest()
    return f"sf.{digest[:24]}"


class GlyfCompositeBuilder:
    """Build one-level composite glyphs and keep metrics synchronized."""

    def __init__(
        self,
        font: TTFont,
        *,
        max_composite_depth: int = 16,
    ) -> None:
        self.font = font
        self.max_composite_depth = max_composite_depth
        self._created: set[str] = set()

    def supports(self) -> bool:
        """Return whether this font can receive ``glyf`` composites."""

        return all(table in self.font for table in ("glyf", "hmtx", "maxp", "head"))

    def _font_error(self, message: str, details: dict[str, object]) -> ShieldFontError:
        return ShieldFontError(
            message,
            code=ErrorCode.FONT_SERIALIZATION,
            exit_code=ExitCode.FONT_SERIALIZATION_ERROR,
            stage="font.glyf-builder",
            details=details,
        )

    def _glyph_depth(self, glyph_name: str, seen: set[str] | None = None) -> int:
        seen = seen or set()
        if glyph_name in seen:
            raise self._font_error(
                "Cyclic composite glyph reference",
                {"glyph": glyph_name},
            )
        glyph = self.font["glyf"][glyph_name]
        components = getattr(glyph, "components", None) or []
        if not components:
            return 0
        next_seen = {*seen, glyph_name}
        return 1 + max(
            self._glyph_depth(component.glyphName, next_seen)
            for component in components
        )

    def create_word_glyph(self, source: str, glyph_name: str) -> GlyphBuildResult:
        """Create a composite whose components preserve source glyph advances."""

        if not self.supports():
            raise self._font_error("Font lacks required TrueType tables", {})
        if not source:
            raise self._font_error("Composite source must not be empty", {})
        if glyph_name in self.font.getGlyphOrder() or glyph_name in self._created:
            raise self._font_error(
                "Generated glyph name already exists",
                {"glyph": glyph_name},
            )
        cmap = self.font.getBestCmap() or {}
        component_names: list[str] = []
        missing: list[str] = []
        for character in source:
            component_name = cmap.get(ord(character))
            if component_name is None:
                missing.append(f"U+{ord(character):04X}")
            else:
                component_names.append(component_name)
        if missing:
            raise self._font_error(
                "Composite source contains code points missing from cmap",
                {"source": source, "missingCodePoints": missing},
            )
        component_depth = max(
            (self._glyph_depth(name) for name in component_names),
            default=0,
        )
        if component_depth + 1 > self.max_composite_depth:
            raise self._font_error(
                "Composite glyph depth exceeds configured limit",
                {"depth": component_depth + 1, "limit": self.max_composite_depth},
            )
        glyph = Glyph()
        glyph.numberOfContours = -1
        glyph.components = []
        advance_width = 0
        for index, component_name in enumerate(component_names):
            component = GlyphComponent()
            component.glyphName = component_name
            component.flags = 0x0004 | 0x0002
            if index < len(component_names) - 1:
                component.flags |= 0x0020
            component.x = advance_width
            component.y = 0
            glyph.components.append(component)
            advance_width += int(self.font["hmtx"].metrics[component_name][0])
        glyph.recalcBounds(self.font["glyf"])
        bounds = (
            int(glyph.xMin),
            int(glyph.xMax),
            int(glyph.yMin),
            int(glyph.yMax),
        )
        if any(value < -32768 or value > 32767 for value in bounds):
            raise self._font_error(
                "Composite glyph bounds exceed signed TrueType limits",
                {"glyph": glyph_name, "bounds": bounds},
            )
        if advance_width < 0 or advance_width > 65535:
            raise self._font_error(
                "Composite advance width exceeds unsigned TrueType limits",
                {"glyph": glyph_name, "advanceWidth": advance_width},
            )
        lsb = int(glyph.xMin)
        self.font["glyf"].glyphs[glyph_name] = glyph
        self.font["hmtx"].metrics[glyph_name] = (advance_width, lsb)
        self.font.setGlyphOrder([*self.font.getGlyphOrder(), glyph_name])
        self._created.add(glyph_name)
        LOGGER.debug("[FIX] Created composite glyph %s", glyph_name)
        return GlyphBuildResult(
            glyph_name=glyph_name,
            source=source,
            advance_width=advance_width,
            lsb=lsb,
            x_min=bounds[0],
            x_max=bounds[1],
            y_min=bounds[2],
            y_max=bounds[3],
            component_count=len(component_names),
        )

    def finalize(self) -> None:
        """Update glyph count and horizontal metric count before serialization."""

        if not self.supports():
            raise self._font_error("Font lacks required TrueType tables", {})
        glyph_count = len(self.font.getGlyphOrder())
        self.font["maxp"].numGlyphs = glyph_count
        if "hhea" in self.font:
            self.font["hhea"].numberOfHMetrics = len(self.font["hmtx"].metrics)
