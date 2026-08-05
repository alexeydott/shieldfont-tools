"""Canonical scope-aware ruleset contract shared by all build stages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shieldfont.domain.dictionary.models import DictionaryEntry, NormalizedDictionary
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError


@dataclass(frozen=True, slots=True)
class CanonicalRule:
    """A serialized mapping rule without filesystem-specific provenance."""

    source: str
    target: str
    case_mode: str
    priority: int
    tags: tuple[str, ...]

    @classmethod
    def from_entry(cls, entry: DictionaryEntry) -> CanonicalRule:
        return cls(
            source=entry.source,
            target=entry.target,
            case_mode=entry.case_mode.value,
            priority=entry.priority,
            tags=entry.tags,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "caseMode": self.case_mode,
            "priority": self.priority,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class ScopeRecord:
    """Canonical mapping and shaping metadata for one configured scope."""

    scope_id: str
    locales: tuple[str, ...]
    source_scripts: tuple[str, ...]
    target_scripts: tuple[str, ...]
    open_type_script: str
    default_language: bool
    languages: tuple[str, ...]
    rules: tuple[CanonicalRule, ...]
    mapping_hash: str

    @classmethod
    def from_dictionary(
        cls,
        *,
        scope_id: str,
        locales: Sequence[str],
        source_scripts: Sequence[str],
        target_scripts: Sequence[str],
        open_type_script: str,
        default_language: bool,
        languages: Sequence[str],
        dictionary: NormalizedDictionary,
    ) -> ScopeRecord:
        rules = tuple(CanonicalRule.from_entry(entry) for entry in dictionary.entries)
        return cls(
            scope_id=scope_id,
            locales=tuple(sorted(set(locales))),
            source_scripts=tuple(sorted(set(source_scripts))),
            target_scripts=tuple(sorted(set(target_scripts))),
            open_type_script=open_type_script,
            default_language=default_language,
            languages=tuple(sorted(set(languages))),
            rules=rules,
            mapping_hash=dictionary.mapping_hash,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.scope_id,
            "locales": list(self.locales),
            "sourceScripts": list(self.source_scripts),
            "targetScripts": list(self.target_scripts),
            "openTypeScript": self.open_type_script,
            "defaultLanguage": self.default_language,
            "languages": list(self.languages),
            "mappingHash": self.mapping_hash,
            "pairs": len(self.rules),
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class NormalizedRuleset:
    """Deterministic, immutable ruleset consumed by font and codec stages."""

    schema: str
    scopes: tuple[ScopeRecord, ...]
    ruleset_hash: str

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": self.schema,
            "scopes": [scope.to_dict() for scope in self.scopes],
        }
        if include_hash:
            payload["rulesetHash"] = self.ruleset_hash
        return payload

    def to_json(self) -> str:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def resolve_scope(
        self,
        *,
        locale: str | None = None,
        script: str | None = None,
        policy: str = "fallback",
    ) -> ScopeRecord | None:
        """Resolve a scope using exact locale, language, script, and default ranks."""

        normalized_locale = locale.replace("_", "-").lower() if locale else None
        normalized_script = script.lower() if script else None
        candidates: list[tuple[int, ScopeRecord]] = []
        for scope in self.scopes:
            scope_locales = {value.lower() for value in scope.locales}
            scope_scripts = {
                value.lower()
                for value in (*scope.source_scripts, *scope.target_scripts)
            }
            rank = 100
            if normalized_locale and normalized_locale in scope_locales:
                rank = 0
            elif normalized_locale and normalized_locale.split("-", 1)[0] in {
                value.split("-", 1)[0] for value in scope_locales
            }:
                rank = 10
            elif normalized_script and normalized_script in scope_scripts:
                rank = 20
            elif scope.default_language:
                rank = 30
            elif scope.open_type_script.lower() == "dflt":
                rank = 40
            if rank < 100:
                candidates.append((rank, scope))
        if not candidates:
            if policy == "no-op":
                return None
            if policy == "error":
                raise ShieldFontError(
                    "No dictionary scope matches the requested context",
                    code=ErrorCode.INVALID_INPUT,
                    exit_code=ExitCode.INVALID_INPUT,
                    stage="ruleset.scope-resolution",
                    details={"locale": locale, "script": script},
                )
            return None
        best_rank = min(rank for rank, _ in candidates)
        best = sorted(
            (scope for rank, scope in candidates if rank == best_rank),
            key=lambda scope: scope.scope_id,
        )
        if len(best) > 1 and policy == "error":
            raise ShieldFontError(
                "Multiple dictionary scopes match the requested context",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="ruleset.scope-resolution",
                details={
                    "locale": locale,
                    "script": script,
                    "scopes": [scope.scope_id for scope in best],
                },
            )
        return best[0]


def build_ruleset(scopes: Sequence[ScopeRecord]) -> NormalizedRuleset:
    """Build a canonical ruleset and derive its content hash."""

    ordered_scopes = tuple(sorted(scopes, key=lambda scope: scope.scope_id))
    payload = {
        "schema": "shieldfont-ruleset/v1",
        "scopes": [scope.to_dict() for scope in ordered_scopes],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    ruleset_hash = f"sha256:{hashlib.sha256(serialized).hexdigest()}"
    return NormalizedRuleset(
        schema="shieldfont-ruleset/v1",
        scopes=ordered_scopes,
        ruleset_hash=ruleset_hash,
    )


def ruleset_from_mapping(
    scopes: Mapping[str, tuple[ScopeRecord, NormalizedDictionary]],
) -> NormalizedRuleset:
    """Build a ruleset while ensuring the scope key and record agree."""

    records: list[ScopeRecord] = []
    for scope_id, (record, dictionary) in scopes.items():
        if record.scope_id != scope_id:
            raise ShieldFontError(
                "Scope record identifier does not match its registry key",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="ruleset.build",
                details={"key": scope_id, "record": record.scope_id},
            )
        records.append(
            ScopeRecord(
                scope_id=record.scope_id,
                locales=record.locales,
                source_scripts=record.source_scripts,
                target_scripts=record.target_scripts,
                open_type_script=record.open_type_script,
                default_language=record.default_language,
                languages=record.languages,
                rules=tuple(
                    CanonicalRule.from_entry(entry) for entry in dictionary.entries
                ),
                mapping_hash=dictionary.mapping_hash,
            )
        )
    return build_ruleset(records)
