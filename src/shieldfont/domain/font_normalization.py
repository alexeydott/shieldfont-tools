"""Font normalization result contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FontNormalizationResult:
    """Metadata emitted after producing a static normalized font."""

    input_path: str
    output_path: str
    variable_input: bool
    instanced: bool
    selected_axes: dict[str, float]
    family: str
    subfamily: str
    post_script_name: str
    removed_tables: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "input": self.input_path,
            "output": self.output_path,
            "variableInput": self.variable_input,
            "instanced": self.instanced,
            "selectedAxes": self.selected_axes,
            "family": self.family,
            "subfamily": self.subfamily,
            "postScriptName": self.post_script_name,
            "removedTables": list(self.removed_tables),
            "warnings": list(self.warnings),
        }
