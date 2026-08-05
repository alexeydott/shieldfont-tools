from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "upstream"
UPSTREAM = ROOT / "deps" / "shieldfont"
WORD_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _preserve_case(source: str, target: str) -> str:
    if len(source) > 1 and source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _reference_encode(text: str, mapping: dict[str, str]) -> str:
    normalized = unicodedata.normalize("NFC", text)
    encoded = WORD_RE.sub(
        lambda match: _preserve_case(
            match.group(0),
            mapping.get(match.group(0).lower(), match.group(0)),
        ),
        normalized,
    )
    characters = list(encoded)
    for index, character in enumerate(characters):
        target = mapping.get(character)
        if target is None or not character.isdigit() or not target.isdigit():
            continue
        left_is_letter = index > 0 and characters[index - 1].isalpha()
        right_is_letter = (
            index + 1 < len(characters) and characters[index + 1].isalpha()
        )
        if int(left_is_letter) + int(right_is_letter) != 1:
            characters[index] = target
    return "".join(characters)


def test_upstream_sources_match_pinned_provenance() -> None:
    provenance = _load_fixture("provenance.json")
    commit = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert commit == provenance["commit"]
    for relative_path, expected_hash in provenance["sources"].items():
        digest = hashlib.sha256((UPSTREAM / relative_path).read_bytes()).hexdigest()
        assert digest == expected_hash


def test_encoder_observations_are_involutive() -> None:
    fixture = _load_fixture("encoder_contract.json")
    mapping: dict[str, str] = fixture["mapping"]

    assert all(mapping.get(target) == source for source, target in mapping.items())
    for case in fixture["cases"]:
        encoded = _reference_encode(case["input"], mapping)
        assert encoded == case["encoded"]
        assert _reference_encode(encoded, mapping) == unicodedata.normalize(
            "NFC", case["input"]
        )


def test_encoder_and_font_directions_are_inverse() -> None:
    fixture = _load_fixture("encoder_contract.json")

    for case in fixture["direction"]:
        assert case["plain_source"] != case["encoder_output"]
        assert case["font_input"] == case["encoder_output"]
        assert case["font_visual_output"] == case["plain_source"]
        assert case["expected_glyph_role"] == "source composite"


def test_fire_then_revert_and_chunking_contract() -> None:
    fixture = _load_fixture("font_layout_contract.json")
    layout = fixture["fire_then_revert"]
    chunking = fixture["chunking"]

    assert layout["lookup_order"][0] == "ligature_substitution"
    assert layout["internal_only_lookup"] not in {
        "ligature_substitution",
        "digit_single_substitution",
        "letter_before_reverter",
        "letter_after_reverter",
    }
    assert {case["expected"] for case in layout["cases"]} == {
        "source composite",
        "plain letters",
    }
    assert chunking["ligature_subtable_budget_bytes"] < 65536
    assert chunking["maximum_reverts_per_subtable"] == 1500
    assert chunking["ligatures_with_common_prefix"] == "longest-first"
    assert chunking["coverage_order"] == "glyph-id"


def test_composite_lsb_must_equal_xmin() -> None:
    fixture = _load_fixture("font_layout_contract.json")

    for case in fixture["composite_metrics"]:
        assert case["damaged"] is (case["lsb"] != case["xMin"])


def test_version_one_scope_is_truetype_only() -> None:
    fixture = _load_fixture("scope_contract.json")

    assert all("glyf" in case["tables"] for case in fixture["accepted"])
    assert all(case["container"] in {"ttf", "woff2"} for case in fixture["accepted"])
    assert all(
        case["container"] not in {"ttf", "woff2"} or "glyf" not in case["tables"]
        for case in fixture["rejected"]
    )
    assert fixture["output"] == {
        "containers": ["ttf", "woff2"],
        "required_table": "glyf",
        "variable": False,
    }
