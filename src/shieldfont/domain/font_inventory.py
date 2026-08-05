"""Framework-independent font inspection result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FontInspection:
    """Human-readable and machine-readable source font inventory."""

    path: str
    container: str
    sfnt_version: str
    tables: tuple[str, ...]
    has_glyf: bool
    variable: bool
    axes: dict[str, float]
    instances: tuple[dict[str, Any], ...]
    names: dict[str, str]
    cmap_codepoints: tuple[int, ...]
    scripts: tuple[str, ...]
    glyph_count: int
    gsub_features: tuple[str, ...]
    gpos_features: tuple[str, ...]
    scripts_languages: dict[str, tuple[str, ...]]
    license_names: dict[str, str]
    has_dsig: bool
    planned_changes: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "container": self.container,
            "sfntVersion": self.sfnt_version,
            "tables": list(self.tables),
            "outlines": {"type": "glyf" if self.has_glyf else "unsupported"},
            "variable": self.variable,
            "axes": self.axes,
            "instances": list(self.instances),
            "names": self.names,
            "cmap": {
                "codePoints": [f"U+{value:04X}" for value in self.cmap_codepoints],
                "count": len(self.cmap_codepoints),
            },
            "scripts": list(self.scripts),
            "glyphCount": self.glyph_count,
            "layout": {
                "gsubFeatures": list(self.gsub_features),
                "gposFeatures": list(self.gpos_features),
                "scriptsLanguages": {
                    script: list(languages)
                    for script, languages in self.scripts_languages.items()
                },
            },
            "license": self.license_names,
            "hasDsig": self.has_dsig,
            "plannedChanges": list(self.planned_changes),
            "warnings": list(self.warnings),
        }
