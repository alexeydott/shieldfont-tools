"""Application service for deterministic feature source generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from shieldfont.domain.features import FeaturePlan, build_fire_then_revert_plan
from shieldfont.domain.ruleset import CanonicalRule, ScopeRecord


def opaque_source_glyph_name(scope_id: str, source: str) -> str:
    """Create the same deterministic opaque naming shape used by glyph builds."""

    digest = hashlib.sha256(
        f"feature\0{scope_id}\0{source}".encode()
    ).hexdigest()
    return f"sf.{digest[:24]}"


def generate_feature_artifacts(
    scope: ScopeRecord,
    *,
    glyph_for_target: Callable[[str], str],
    glyph_for_source: Callable[[str], str],
    glyph_for_source_variant: Callable[[str, str], str] | None = None,
    glyph_id: Callable[[str], int] | None = None,
    output_dir: Path,
    stem: str,
    lookup_prefix: str = "sf",
) -> dict[str, Path]:
    """Write human-readable FEA and machine-readable layout plan artifacts."""

    plan: FeaturePlan = build_fire_then_revert_plan(
        scope,
        glyph_for_target=glyph_for_target,
        glyph_for_source=glyph_for_source,
        glyph_for_source_variant=glyph_for_source_variant,
        glyph_id=glyph_id,
        lookup_prefix=lookup_prefix,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fea_path = output_dir / f"{stem}.fea"
    plan_path = output_dir / f"{stem}.layout.json"
    fea_path.write_text(plan.to_fea(), encoding="utf-8")
    plan_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"fea": fea_path, "plan": plan_path}


def load_scope_from_ruleset(path: Path, scope_id: str) -> ScopeRecord:
    """Load one canonical scope from a serialized ruleset artifact."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    scopes = [
        scope for scope in payload.get("scopes", []) if scope.get("id") == scope_id
    ]
    if len(scopes) != 1:
        raise ValueError(f"Ruleset does not contain a unique scope: {scope_id}")
    scope = scopes[0]
    return ScopeRecord(
        scope_id=scope["id"],
        locales=tuple(scope.get("locales", [])),
        source_scripts=tuple(scope.get("sourceScripts", [])),
        target_scripts=tuple(scope.get("targetScripts", [])),
        open_type_script=scope["openTypeScript"],
        default_language=bool(scope.get("defaultLanguage", False)),
        languages=tuple(scope.get("languages", [])),
        rules=tuple(
            CanonicalRule(
                source=rule["source"],
                target=rule["target"],
                case_mode=rule.get("caseMode", "auto"),
                priority=int(rule.get("priority", 0)),
                tags=tuple(rule.get("tags", [])),
            )
            for rule in scope.get("rules", [])
        ),
        mapping_hash=scope.get("mappingHash", ""),
    )
