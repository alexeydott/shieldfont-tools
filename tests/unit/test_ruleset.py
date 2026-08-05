from __future__ import annotations

import json
from pathlib import Path

import pytest

from shieldfont.application.ruleset import build_ruleset_from_config
from shieldfont.config.models import ScopeSection, ShieldFontConfig
from shieldfont.domain.dictionary.models import (
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
)
from shieldfont.domain.dictionary.validation import normalize_dictionary
from shieldfont.domain.errors import ShieldFontError
from shieldfont.domain.manifest import BuildManifest
from shieldfont.domain.ruleset import ScopeRecord, build_ruleset


def _scope(
    scope_id: str,
    *,
    locale: str,
    script: str,
    default_language: bool = False,
) -> ScopeRecord:
    dictionary = normalize_dictionary(
        [DictionaryEntry("source", "target"), DictionaryEntry("target", "source")],
        policy=DictionaryPolicy(mapping_mode=MappingMode.INVOLUTION),
    )
    return ScopeRecord.from_dictionary(
        scope_id=scope_id,
        locales=(locale,),
        source_scripts=(script,),
        target_scripts=(script,),
        open_type_script=script,
        default_language=default_language,
        languages=("dflt",),
        dictionary=dictionary,
    )


def test_ruleset_is_sorted_and_scope_resolution_is_deterministic() -> None:
    ruleset = build_ruleset((_scope("ru", locale="ru-RU", script="cyrl"), _scope(
        "en",
        locale="en-US",
        script="latn",
        default_language=True,
    )))

    assert [scope.scope_id for scope in ruleset.scopes] == ["en", "ru"]
    assert ruleset.to_dict()["schema"] == "shieldfont-ruleset/v1"
    assert ruleset.resolve_scope(locale="ru").scope_id == "ru"
    assert ruleset.resolve_scope(locale="unknown", policy="no-op") is not None
    assert ruleset.ruleset_hash.startswith("sha256:")


def test_ruleset_from_config_uses_mapping_contract() -> None:
    config = ShieldFontConfig(
        scopes=[
            ScopeSection(
                id="latin",
                encoder={"locales": ["en-US"], "sourceScripts": ["Latn"]},
                shaping={
                    "targetScripts": ["Latn"],
                    "openTypeScript": "latn",
                    "defaultLanguage": True,
                },
            )
        ]
    )
    ruleset = build_ruleset_from_config(
        config,
        {
            "latin": [
                DictionaryEntry("source", "target"),
                DictionaryEntry("target", "source"),
            ]
        },
    )

    assert ruleset.scopes[0].mapping_hash.startswith("sha256:")


def test_manifest_build_id_is_content_derived() -> None:
    manifest = BuildManifest.create(
        project_id="example",
        project_version="1.0.0",
        tool_version="0.1.0",
        source={"path": "fonts/source.ttf"},
        font={"family": "Example"},
        scopes=[{"id": "latin", "mappingHash": "sha256:test", "pairs": 2}],
    )
    parsed = json.loads(manifest.to_json())

    assert parsed["schema"] == "shieldfont-build/v1"
    assert manifest.build_id.startswith("sha256:")
    assert parsed["buildId"] == manifest.build_id


def test_canonical_ruleset_matches_shared_fixture() -> None:
    ruleset = build_ruleset(
        (_scope("en", locale="en-US", script="latn", default_language=True),)
    )
    fixture = json.loads(
        Path("tests/fixtures/canonical/ruleset-v1.json").read_text(encoding="utf-8")
    )

    assert ruleset.to_dict() == fixture


def test_scope_resolution_errors_on_ambiguous_best_match() -> None:
    ruleset = build_ruleset(
        (
            _scope("a", locale="en-US", script="latn"),
            _scope("b", locale="en-US", script="latn"),
        )
    )

    with pytest.raises(ShieldFontError):
        ruleset.resolve_scope(locale="en-US", policy="error")
