"""Deterministic OpenType feature plan and source contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.ruleset import ScopeRecord


@dataclass(frozen=True, slots=True)
class FeatureRule:
    """One glyph substitution rule in canonical target order."""

    target_glyphs: tuple[str, ...]
    replacement: str
    source: str

    def to_fea(self) -> str:
        if len(self.target_glyphs) == 1:
            return f"sub {self.target_glyphs[0]} by {self.replacement};"
        return f"sub {' '.join(self.target_glyphs)} by {self.replacement};"


@dataclass(frozen=True, slots=True)
class LookupPlan:
    """A named deterministic lookup block."""

    name: str
    lookup_type: str
    rules: tuple[FeatureRule, ...]
    internal: bool = False

    def to_fea(self) -> str:
        lines = [f"lookup {self.name} {{"]
        lines.extend(f"  {rule.to_fea()}" for rule in self.rules)
        lines.append(f"}} {self.name};")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class FeaturePlan:
    """Public feature and script/language attachment plan."""

    feature_tag: str
    scripts: tuple[str, ...]
    language_systems: tuple[tuple[str, str], ...]
    lookups: tuple[LookupPlan, ...]

    def to_fea(self) -> str:
        lines: list[str] = []
        for script, language in self.language_systems:
            lines.append(f"languagesystem {script} {language};")
        lines.append("")
        for lookup in self.lookups:
            lines.append(lookup.to_fea())
            lines.append("")
        lines.append(f"feature {self.feature_tag} {{")
        for lookup in self.lookups:
            if not lookup.internal:
                lines.append(f"  lookup {lookup.name};")
        lines.append(f"}} {self.feature_tag};")
        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature_tag,
            "scripts": list(self.scripts),
            "languageSystems": [
                {"script": script, "language": language}
                for script, language in self.language_systems
            ],
            "lookups": [
                {
                    "name": lookup.name,
                    "type": lookup.lookup_type,
                    "internal": lookup.internal,
                    "rules": [
                        {
                            "targetGlyphs": list(rule.target_glyphs),
                            "replacement": rule.replacement,
                            "source": rule.source,
                        }
                        for rule in lookup.rules
                    ],
                }
                for lookup in self.lookups
            ],
        }


def build_fire_then_revert_plan(
    scope: ScopeRecord,
    *,
    glyph_for_target: Callable[[str], str],
    glyph_for_source: Callable[[str], str],
    glyph_for_source_variant: Callable[[str, str], str] | None = None,
    glyph_id: Callable[[str], int] | None = None,
    feature_tag: str = "ccmp",
    lookup_prefix: str = "sf",
) -> FeaturePlan:
    """Build longest-first ligatures followed by internal reversion lookups."""

    rules: list[FeatureRule] = []
    seen_target_glyphs: set[tuple[str, ...]] = set()
    for canonical_rule in scope.rules:
        variants = {
            "exact": (("", canonical_rule.source, canonical_rule.target),),
            "lower": ((
                "lower",
                canonical_rule.source.lower(),
                canonical_rule.target.lower(),
            ),),
            "title": ((
                "title",
                canonical_rule.source.title(),
                canonical_rule.target.title(),
            ),),
            "upper": ((
                "upper",
                canonical_rule.source.upper(),
                canonical_rule.target.upper(),
            ),),
            "all": tuple(
                (mode, getattr(canonical_rule.source, mode)(), getattr(
                    canonical_rule.target,
                    mode,
                )())
                for mode in ("lower", "title", "upper")
            )
            ,
            "auto": (
                ("", canonical_rule.source, canonical_rule.target),
                ("lower", canonical_rule.source.lower(), canonical_rule.target.lower()),
                ("title", canonical_rule.source.title(), canonical_rule.target.title()),
                ("upper", canonical_rule.source.upper(), canonical_rule.target.upper()),
            ),
        }[canonical_rule.case_mode]
        seen_variants: set[tuple[str, str]] = set()
        for variant, source, target in variants:
            if (source, target) in seen_variants:
                continue
            seen_variants.add((source, target))
            target_glyphs = tuple(glyph_for_target(character) for character in target)
            if not target_glyphs:
                raise ShieldFontError(
                    "Feature rule target must contain at least one glyph",
                    code=ErrorCode.FEATURE_GENERATION_ERROR,
                    exit_code=ExitCode.FEATURE_GENERATION_ERROR,
                    stage="features.plan",
                    details={"source": canonical_rule.source},
                )
            if target_glyphs in seen_target_glyphs:
                continue
            seen_target_glyphs.add(target_glyphs)
            replacement = (
                glyph_for_source_variant(source, variant)
                if glyph_for_source_variant is not None
                else glyph_for_source(source)
            )
            rules.append(
                FeatureRule(
                    target_glyphs=target_glyphs,
                    replacement=replacement,
                    source=source,
                )
            )
    rules.sort(
        key=lambda rule: (
            -len(rule.target_glyphs),
            tuple(glyph_id(glyph) for glyph in rule.target_glyphs)
            if glyph_id is not None
            else rule.target_glyphs,
            rule.source,
        )
    )
    revert_rules = tuple(
        FeatureRule(
            target_glyphs=(rule.replacement,),
            replacement=" ".join(rule.target_glyphs),
            source=rule.source,
        )
        for rule in rules
    )
    return FeaturePlan(
        feature_tag=feature_tag,
        scripts=(scope.open_type_script,),
        language_systems=tuple(
            [(scope.open_type_script, "dflt")]
            + [
                (scope.open_type_script, language)
                for language in sorted(set(scope.languages))
                if language.lower() != "dflt"
            ]
        ),
        lookups=(
            LookupPlan(f"{lookup_prefix}_ligatures", "ligature", tuple(rules)),
            LookupPlan(
                f"{lookup_prefix}_revert_multiple",
                "multiple",
                revert_rules,
                internal=True,
            ),
            LookupPlan(
                f"{lookup_prefix}_revert_before",
                "context",
                revert_rules,
            ),
            LookupPlan(
                f"{lookup_prefix}_revert_after",
                "context",
                revert_rules,
            ),
        ),
    )
