from __future__ import annotations

import json
from pathlib import Path

import pytest

from shieldfont.application.dictionary import write_dictionary_artifacts
from shieldfont.domain.dictionary.models import (
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
    validate_glyph_coverage,
)
from shieldfont.domain.errors import ErrorCode, ShieldFontError
from shieldfont.infrastructure.dictionary.csv_reader import read_csv_dictionary


def _pair(source: str, target: str, *, priority: int = 0) -> list[DictionaryEntry]:
    return [
        DictionaryEntry(source, target, priority=priority),
        DictionaryEntry(target, source, priority=priority),
    ]


def test_csv_reader_accepts_bom_aliases_and_extended_fields(tmp_path: Path) -> None:
    path = tmp_path / "aliases.csv"
    path.write_text(
        "key,value,enabled,case_mode,priority,tags,comment\n"
        " cafe\u0301 ,déjà,true,upper,7,one; two,note\n"
        "ignored,ignored,false,auto,0,,\n",
        encoding="utf-8-sig",
    )

    entries = read_csv_dictionary(path)

    assert entries[0].source == " cafe\u0301 "
    assert entries[0].case_mode.value == "upper"
    assert entries[0].priority == 7
    assert entries[0].tags == ("one", "two")
    assert entries[1].enabled is False


def test_normalizer_applies_nfc_trim_and_canonical_order() -> None:
    dictionary = normalize_dictionary(
        _pair(" cafe\u0301 ", " long target ")
        + _pair("short", "tiny"),
        policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
    )

    assert [(entry.source, entry.target) for entry in dictionary.entries] == [
        ("café", "long target"),
        ("tiny", "short"),
        ("long target", "café"),
        ("short", "tiny"),
    ]
    assert dictionary.mapping_hash.startswith("sha256:")


def test_target_collision_reports_origin() -> None:
    first = Path("first.csv")
    entries = [
        DictionaryEntry("one", "same", origin_file=first, origin_line=4),
        DictionaryEntry("two", "same", origin_file=first, origin_line=5),
    ]

    with pytest.raises(ShieldFontError) as error:
        normalize_dictionary(
            entries,
            policy=DictionaryPolicy(
                mapping_mode=MappingMode.DIRECTED,
                target_collision_policy="error",
            ),
        )

    assert error.value.code is ErrorCode.DICTIONARY_TARGET_COLLISION
    assert error.value.details["line"] == 4


def test_involution_requires_reverse_pair() -> None:
    with pytest.raises(ShieldFontError) as error:
        normalize_dictionary(
            [DictionaryEntry("source", "target")],
            policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
        )

    assert error.value.code is ErrorCode.DICTIONARY_INVOLUTION


def test_merge_prefers_later_layer_when_priorities_match() -> None:
    merged = merge_dictionaries(
        [_pair("word", "base"), _pair("word", "override")],
        policy=DictionaryPolicy(
            mapping_mode=MappingMode.INVOLUTION,
            target_collision_policy="error",
        ),
    )

    assert {entry.source: entry.target for entry in merged.entries} == {
        "word": "override",
        "override": "word",
    }


def test_artifacts_use_maps_and_reports_layout(tmp_path: Path) -> None:
    dictionary = normalize_dictionary(
        _pair("a", "b"),
        policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
    )

    artifacts = write_dictionary_artifacts(
        dictionary,
        output_dir=tmp_path / "dist",
        stem="latin",
    )

    assert artifacts["csv"] == tmp_path / "dist/maps/latin.csv"
    assert artifacts["report"] == tmp_path / "dist/reports/latin.dictionary.json"
    assert json.loads(artifacts["inverse"].read_text(encoding="utf-8")) == {
        "a": "b",
        "b": "a",
    }


def test_glyph_coverage_hook_rejects_missing_code_points() -> None:
    dictionary = normalize_dictionary(
        _pair("a", "b"),
        policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
    )

    with pytest.raises(ShieldFontError) as error:
        validate_glyph_coverage(
            dictionary,
            glyph_exists=lambda codepoint: codepoint == ord("a"),
        )

    assert "U+0062" in error.value.details["missingCodePoints"]


def test_cross_scope_conflicts_are_deterministic() -> None:
    left = normalize_dictionary(
        _pair("word", "mot"),
        policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
    )
    right = NormalizedDictionary(
        entries=(DictionaryEntry("word", "slovo"), DictionaryEntry("slovo", "word")),
    )

    conflicts = find_cross_scope_conflicts(
        (
            ScopeDictionary("en", left, "latn", ("en",)),
            ScopeDictionary("ru", right, "latn", ("en",)),
        )
    )

    assert {conflict["kind"] for conflict in conflicts} == {
        "source-conflict",
        "target-collision",
    }
