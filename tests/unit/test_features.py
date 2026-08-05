from __future__ import annotations

from shieldfont.domain.dictionary.models import (
    CaseMode,
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
)
from shieldfont.domain.dictionary.validation import normalize_dictionary
from shieldfont.domain.features import build_fire_then_revert_plan
from shieldfont.domain.ruleset import ScopeRecord


def test_fire_then_revert_plan_is_longest_first_and_keeps_revert_internal() -> None:
    dictionary = normalize_dictionary(
        [
            DictionaryEntry("short", "ab", case_mode=CaseMode.EXACT),
            DictionaryEntry("long", "abc", case_mode=CaseMode.EXACT),
        ],
        policy=DictionaryPolicy(
            mapping_mode=MappingMode.DIRECTED,
            target_collision_policy="error",
        ),
    )
    scope = ScopeRecord.from_dictionary(
        scope_id="latin",
        locales=("en-US",),
        source_scripts=("latn",),
        target_scripts=("latn",),
        open_type_script="latn",
        default_language=True,
        languages=(),
        dictionary=dictionary,
    )

    plan = build_fire_then_revert_plan(
        scope,
        glyph_for_target=lambda character: f"g_{character}",
        glyph_for_source=lambda source: f"sf_{source}",
        glyph_id=lambda glyph: len(glyph),
    )

    assert [rule.source for rule in plan.lookups[0].rules] == ["long", "short"]
    assert plan.lookups[1].internal is True
    assert "languagesystem latn dflt;" in plan.to_fea()
    assert "lookup sf_revert_multiple;" not in plan.to_fea()
