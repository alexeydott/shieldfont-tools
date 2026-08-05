"""Deterministic GSUB lookup chunking contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.features import FeaturePlan, FeatureRule, LookupPlan

LIGATURE_SUBTABLE_BUDGET = 40 * 1024
MAX_REVERTS_PER_SUBTABLE = 1500


def estimate_ligature_rule_bytes(rule: FeatureRule) -> int:
    """Conservatively estimate one ligature record's encoded footprint."""

    return 16 + len(rule.replacement) + sum(
        len(glyph) + 2 for glyph in rule.target_glyphs
    )


def _chunk_rules(
    rules: tuple[FeatureRule, ...],
    *,
    limit: int,
    estimate: Callable[[FeatureRule], int],
) -> tuple[tuple[FeatureRule, ...], ...]:
    chunks: list[tuple[FeatureRule, ...]] = []
    current: list[FeatureRule] = []
    current_size = 0
    for rule in rules:
        size = estimate(rule)
        if size > limit:
            raise ShieldFontError(
                "A single GSUB rule exceeds the configured subtable budget",
                code=ErrorCode.GSUB_COMPILE_ERROR,
                exit_code=ExitCode.GSUB_COMPILE_ERROR,
                stage="gsub.chunk",
                details={"estimatedBytes": size, "limit": limit},
            )
        if current and current_size + size > limit:
            chunks.append(tuple(current))
            current = []
            current_size = 0
        current.append(rule)
        current_size += size
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def chunk_feature_plan(
    plan: FeaturePlan,
    *,
    ligature_budget: int = LIGATURE_SUBTABLE_BUDGET,
    max_reverts: int = MAX_REVERTS_PER_SUBTABLE,
) -> FeaturePlan:
    """Split large lookups while preserving their canonical order."""

    lookups: list[LookupPlan] = []
    for lookup in plan.lookups:
        if lookup.lookup_type == "ligature":
            chunks = _chunk_rules(
                lookup.rules,
                limit=ligature_budget,
                estimate=estimate_ligature_rule_bytes,
            )
        elif lookup.lookup_type in {"multiple", "context"} and "revert" in lookup.name:
            chunks = tuple(
                lookup.rules[index : index + max_reverts]
                for index in range(0, len(lookup.rules), max_reverts)
            )
        else:
            chunks = (lookup.rules,)
        if len(chunks) == 1:
            lookups.append(lookup)
            continue
        for index, rules in enumerate(chunks, start=1):
            lookups.append(
                replace(
                    lookup,
                    name=f"{lookup.name}_{index:03d}",
                    rules=rules,
                )
            )
    return replace(plan, lookups=tuple(lookups))
