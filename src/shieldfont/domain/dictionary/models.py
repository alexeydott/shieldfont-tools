"""Immutable dictionary records and policy types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class CaseMode(StrEnum):
    EXACT = "exact"
    AUTO = "auto"
    LOWER = "lower"
    TITLE = "title"
    UPPER = "upper"
    ALL = "all"


class MappingMode(StrEnum):
    INVOLUTION = "involution"
    BIDIRECTIONAL = "bidirectional"
    DIRECTED = "directed"
    ENCODE_ONLY = "encode-only"
    DECODE_ONLY = "decode-only"


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    """A source-target mapping row with provenance metadata."""

    source: str
    target: str
    enabled: bool = True
    case_mode: CaseMode = CaseMode.AUTO
    priority: int = 0
    tags: tuple[str, ...] = ()
    comment: str = ""
    origin_file: Path | None = None
    origin_line: int | None = None

    def key(self) -> tuple[str, str]:
        return self.source, self.target


@dataclass(frozen=True, slots=True)
class DictionaryPolicy:
    """Validation and normalization behavior."""

    mapping_mode: MappingMode = MappingMode.INVOLUTION
    duplicate_policy: str = "error"
    target_collision_policy: str = "error"
    self_map_policy: str = "drop-with-warning"
    preserve_outer_space: bool = False
    allow_control_characters: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedDictionary:
    """Deterministic dictionary plus diagnostics and hash."""

    entries: tuple[DictionaryEntry, ...]
    warnings: tuple[str, ...] = ()
    source_files: tuple[Path, ...] = ()
    mapping_hash: str = ""
    inverse: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScopeDictionary:
    """A normalized dictionary attached to one shaping scope."""

    scope_id: str
    dictionary: NormalizedDictionary
    open_type_script: str
    locales: tuple[str, ...] = ()
    inherits_default: bool = False
