"""Canonical dictionary domain models and validation policies."""

from shieldfont.domain.dictionary.models import (
    CaseMode,
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
    NormalizedDictionary,
    ScopeDictionary,
)
from shieldfont.domain.dictionary.validation import (
    find_cross_scope_conflicts,
    merge_dictionaries,
    normalize_dictionary,
    validate_dictionary,
    validate_glyph_coverage,
)

__all__ = [
    "CaseMode",
    "DictionaryEntry",
    "DictionaryPolicy",
    "MappingMode",
    "NormalizedDictionary",
    "ScopeDictionary",
    "find_cross_scope_conflicts",
    "merge_dictionaries",
    "normalize_dictionary",
    "validate_glyph_coverage",
    "validate_dictionary",
]
