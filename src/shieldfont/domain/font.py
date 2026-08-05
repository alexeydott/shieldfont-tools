"""Framework-independent font metadata used by application ports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FontSummary:
    """Minimal source-font metadata required by project initialization."""

    family: str
    subfamily: str
    weight: int
    style: str
    has_glyf: bool
    variable: bool
    axes: dict[str, float] = field(default_factory=dict)
