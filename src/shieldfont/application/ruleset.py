"""Application service for building the canonical config-backed ruleset."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.dictionary.models import (
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
)
from shieldfont.domain.dictionary.validation import normalize_dictionary
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.ruleset import NormalizedRuleset, ScopeRecord, build_ruleset


def _mapping_policy(config: ShieldFontConfig) -> DictionaryPolicy:
    mode = {
        "directed": MappingMode.DIRECTED,
        "bidirectional": MappingMode.BIDIRECTIONAL,
        "involution": MappingMode.INVOLUTION,
    }[config.mapping.mode]
    return DictionaryPolicy(
        mapping_mode=mode,
        duplicate_policy=config.mapping.duplicate_policy,
        target_collision_policy=config.mapping.target_collision_policy,
        self_map_policy=config.mapping.self_map_policy,
    )


def build_ruleset_from_config(
    config: ShieldFontConfig,
    dictionaries: Mapping[str, Iterable[DictionaryEntry]],
) -> NormalizedRuleset:
    """Normalize configured dictionaries and bind them to canonical scopes."""

    policy = _mapping_policy(config)
    records: list[ScopeRecord] = []
    for scope in config.scopes:
        raw_dictionary = dictionaries.get(scope.id)
        if raw_dictionary is None:
            raise ShieldFontError(
                "Configured scope has no loaded dictionary",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="ruleset.build",
                details={"scope": scope.id},
            )
        try:
            normalized = normalize_dictionary(raw_dictionary, policy=policy)
        except TypeError as error:
            raise ShieldFontError(
                "Loaded scope dictionary has an invalid shape",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="ruleset.build",
                details={"scope": scope.id},
            ) from error
        records.append(
            ScopeRecord.from_dictionary(
                scope_id=scope.id,
                locales=scope.encoder.locales,
                source_scripts=scope.encoder.source_scripts,
                target_scripts=scope.shaping.target_scripts,
                open_type_script=scope.shaping.open_type_script,
                default_language=scope.shaping.default_language,
                languages=scope.shaping.languages,
                dictionary=normalized,
            )
        )
    return build_ruleset(records)
