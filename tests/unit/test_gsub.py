from __future__ import annotations

from shieldfont.domain.features import FeaturePlan, FeatureRule, LookupPlan
from shieldfont.domain.gsub import (
    MAX_REVERTS_PER_SUBTABLE,
    chunk_feature_plan,
)


def test_large_reversal_lookups_are_chunked_without_reordering() -> None:
    rules = tuple(
        FeatureRule((f"target-{index}",), f"source-{index}", str(index))
        for index in range(MAX_REVERTS_PER_SUBTABLE + 1)
    )
    plan = FeaturePlan(
        feature_tag="ccmp",
        scripts=("latn",),
        language_systems=(("latn", "dflt"),),
        lookups=(
            LookupPlan(
                "sf_revert_multiple",
                "multiple",
                rules,
                internal=True,
            ),
        ),
    )

    chunked = chunk_feature_plan(plan)

    assert len(chunked.lookups) == 2
    assert len(chunked.lookups[0].rules) == MAX_REVERTS_PER_SUBTABLE
    assert chunked.lookups[1].rules[-1].source == str(MAX_REVERTS_PER_SUBTABLE)
