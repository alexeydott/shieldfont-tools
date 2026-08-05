"""Pure dictionary normalization, validation, and merge operations."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from shieldfont.domain.dictionary.models import (
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
    NormalizedDictionary,
    ScopeDictionary,
)
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError


def _normalize_text(value: str, *, preserve_outer_space: bool) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized if preserve_outer_space else normalized.strip()


def _contains_forbidden_content(value: str, *, allow_controls: bool) -> bool:
    if "\n" in value or "\r" in value:
        return True
    forbidden_bidi = {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
    return (
        any(
            unicodedata.category(character) == "Cc"
            and character not in {"\t"}
            for character in value
        )
        or any(character in forbidden_bidi for character in value)
    ) and not allow_controls


def _entry_sort_key(entry: DictionaryEntry) -> tuple[int, tuple[int, ...], str]:
    return (-len(entry.target), tuple(map(ord, entry.target)), entry.source)


def _mapping_hash(entries: Sequence[DictionaryEntry]) -> str:
    payload = [
        {
            "source": entry.source,
            "target": entry.target,
            "caseMode": entry.case_mode.value,
            "priority": entry.priority,
            "tags": list(entry.tags),
        }
        for entry in entries
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _conflict(
    message: str,
    *,
    code: ErrorCode,
    entry: DictionaryEntry,
    details: dict[str, object],
) -> ShieldFontError:
    if entry.origin_file is not None:
        details["file"] = str(entry.origin_file)
    if entry.origin_line is not None:
        details["line"] = entry.origin_line
    return ShieldFontError(
        message,
        code=code,
        exit_code=ExitCode.DICTIONARY_CONFLICT,
        stage="dictionary.validate",
        details=details,
    )


def normalize_dictionary(
    entries: Iterable[DictionaryEntry],
    *,
    policy: DictionaryPolicy | None = None,
) -> NormalizedDictionary:
    """Normalize rows, apply duplicate/self-map policies, and validate mappings."""

    resolved_policy = policy or DictionaryPolicy()
    warnings: list[str] = []
    by_source: dict[str, DictionaryEntry] = {}
    source_files: set[Path] = set()
    for raw_entry in entries:
        source = _normalize_text(
            raw_entry.source,
            preserve_outer_space=resolved_policy.preserve_outer_space,
        )
        target = _normalize_text(
            raw_entry.target,
            preserve_outer_space=resolved_policy.preserve_outer_space,
        )
        entry = DictionaryEntry(
            source=source,
            target=target,
            enabled=raw_entry.enabled,
            case_mode=raw_entry.case_mode,
            priority=raw_entry.priority,
            tags=tuple(
                sorted(
                    {
                        tag.strip()
                        for tag in raw_entry.tags
                        if tag.strip()
                    }
                )
            ),
            comment=raw_entry.comment,
            origin_file=raw_entry.origin_file,
            origin_line=raw_entry.origin_line,
        )
        if entry.origin_file is not None:
            source_files.add(entry.origin_file)
        if not entry.enabled:
            continue
        if not entry.source or not entry.target:
            raise _conflict(
                "Dictionary source and target must not be empty",
                code=ErrorCode.DICTIONARY_PARSE,
                entry=entry,
                details={"source": entry.source, "target": entry.target},
            )
        if _contains_forbidden_content(
            entry.source,
            allow_controls=resolved_policy.allow_control_characters,
        ) or _contains_forbidden_content(
            entry.target,
            allow_controls=resolved_policy.allow_control_characters,
        ):
            raise _conflict(
                "Dictionary entries must not contain control characters or newlines",
                code=ErrorCode.DICTIONARY_PARSE,
                entry=entry,
                details={"source": entry.source},
            )
        if entry.source == entry.target:
            if resolved_policy.self_map_policy == "error":
                raise _conflict(
                    "Self-mapping is not allowed",
                    code=ErrorCode.DICTIONARY_SOURCE_COLLISION,
                    entry=entry,
                    details={"source": entry.source},
                )
            if resolved_policy.self_map_policy == "drop-with-warning":
                warnings.append(f"dropped self-map: {entry.source}")
                continue
        previous = by_source.get(entry.source)
        if previous is not None:
            if previous.target == entry.target:
                warnings.append(f"dropped exact duplicate: {entry.source}")
                if entry.priority > previous.priority:
                    by_source[entry.source] = entry
                continue
            if resolved_policy.duplicate_policy == "error":
                raise _conflict(
                    "Source is mapped to multiple targets",
                    code=ErrorCode.DICTIONARY_SOURCE_COLLISION,
                    entry=entry,
                    details={
                        "source": entry.source,
                        "targets": [previous.target, entry.target],
                    },
                )
            if resolved_policy.duplicate_policy == "first-wins":
                warnings.append(f"kept first source mapping: {entry.source}")
                continue
            if resolved_policy.duplicate_policy == "last-wins":
                warnings.append(f"kept last source mapping: {entry.source}")
                by_source[entry.source] = entry
                continue
            raise ValueError(
                f"Unsupported duplicate policy: {resolved_policy.duplicate_policy}"
            )
        by_source[entry.source] = entry

    by_target: dict[str, list[DictionaryEntry]] = defaultdict(list)
    for entry in by_source.values():
        by_target[entry.target].append(entry)
    entries_list = list(by_source.values())
    for target, collisions in by_target.items():
        if len(collisions) < 2:
            continue
        if resolved_policy.target_collision_policy == "error":
            first = collisions[0]
            raise _conflict(
                "Target is produced by multiple sources",
                code=ErrorCode.DICTIONARY_TARGET_COLLISION,
                entry=first,
                details={
                    "target": target,
                    "sources": sorted(entry.source for entry in collisions),
                },
            )
        if resolved_policy.target_collision_policy == "warn":
            warnings.append(
                f"target collision retained: {target} <- "
                f"{','.join(sorted(entry.source for entry in collisions))}"
            )
            continue
        if resolved_policy.target_collision_policy in {"keep-first", "keep-last"}:
            ordered = sorted(
                collisions,
                key=lambda entry: (entry.priority, entry.source),
            )
            keep = (
                ordered[0]
                if resolved_policy.target_collision_policy == "keep-first"
                else ordered[-1]
            )
            entries_list = [
                entry
                for entry in entries_list
                if entry.target != target or entry.source == keep.source
            ]
            warnings.append(f"resolved target collision: {target}")
            continue
        if resolved_policy.target_collision_policy == "drop-lower-priority":
            keep = max(collisions, key=lambda entry: (entry.priority, entry.source))
            entries_list = [
                entry
                for entry in entries_list
                if entry.target != target or entry.source == keep.source
            ]
            warnings.append(f"dropped lower-priority target collision: {target}")
            continue
        raise ValueError(
            f"Unsupported target collision policy: "
            f"{resolved_policy.target_collision_policy}"
        )

    entries_list.sort(key=_entry_sort_key)
    if resolved_policy.mapping_mode is MappingMode.INVOLUTION:
        mapping = {entry.source: entry.target for entry in entries_list}
        missing = [
            entry
            for entry in entries_list
            if mapping.get(entry.target) != entry.source
        ]
        if missing:
            first = missing[0]
            raise _conflict(
                "Involution mapping requires every pair to have its reverse",
                code=ErrorCode.DICTIONARY_INVOLUTION,
                entry=first,
                details={
                    "source": first.source,
                    "target": first.target,
                    "missingReverse": first.target,
                },
            )

    inverse: dict[str, str] = {}
    if resolved_policy.mapping_mode in {
        MappingMode.INVOLUTION,
        MappingMode.BIDIRECTIONAL,
    }:
        for entry in entries_list:
            inverse_previous = inverse.get(entry.target)
            if inverse_previous is not None and inverse_previous != entry.source:
                raise _conflict(
                    "Inverse mapping is not injective",
                    code=ErrorCode.DICTIONARY_TARGET_COLLISION,
                    entry=entry,
                    details={
                        "target": entry.target,
                        "sources": [inverse_previous, entry.source],
                    },
                )
            inverse[entry.target] = entry.source

    normalized = tuple(entries_list)
    result = NormalizedDictionary(
        entries=normalized,
        warnings=tuple(warnings),
        source_files=tuple(sorted(source_files)),
        mapping_hash=_mapping_hash(normalized),
        inverse=inverse,
    )
    return result


def validate_dictionary(
    entries: Iterable[DictionaryEntry],
    *,
    policy: DictionaryPolicy | None = None,
) -> NormalizedDictionary:
    """Validate and normalize a dictionary without writing artifacts."""

    return normalize_dictionary(entries, policy=policy)


def validate_glyph_coverage(
    dictionary: NormalizedDictionary,
    *,
    glyph_exists: Callable[[int], bool],
) -> None:
    """Reject mappings whose source or target code points lack glyph coverage."""

    for entry in dictionary.entries:
        missing = [
            codepoint
            for value in (entry.source, entry.target)
            for codepoint in map(ord, value)
            if not glyph_exists(codepoint)
        ]
        if missing:
            raise _conflict(
                "Dictionary contains code points missing from the source font",
                code=ErrorCode.DICTIONARY_PARSE,
                entry=entry,
                details={
                    "missingCodePoints": sorted(
                        set(f"U+{value:04X}" for value in missing)
                    ),
                },
            )


def find_cross_scope_conflicts(
    scopes: Sequence[ScopeDictionary],
) -> tuple[dict[str, object], ...]:
    """Return deterministic conflicts between dictionaries sharing scope context."""

    conflicts: list[dict[str, object]] = []
    for index, left in enumerate(scopes):
        left_map = {entry.source: entry.target for entry in left.dictionary.entries}
        left_targets = {
            entry.target: entry.source for entry in left.dictionary.entries
        }
        for right in scopes[index + 1 :]:
            same_script = left.open_type_script == right.open_type_script
            right_map = {
                entry.source: entry.target for entry in right.dictionary.entries
            }
            if same_script:
                for target in sorted(
                    set(left_targets).intersection(
                        entry.target for entry in right.dictionary.entries
                    )
                ):
                    right_sources = sorted(
                        entry.source
                        for entry in right.dictionary.entries
                        if entry.target == target
                    )
                    if left_targets[target] not in right_sources:
                        conflicts.append(
                            {
                                "kind": "target-collision",
                                "target": target,
                                "scopes": [left.scope_id, right.scope_id],
                            }
                        )
            overlapping_locales = sorted(
                set(left.locales).intersection(right.locales)
            )
            for source in sorted(set(left_map).intersection(right_map)):
                if left_map[source] != right_map[source] and overlapping_locales:
                    conflicts.append(
                        {
                            "kind": "source-conflict",
                            "source": source,
                            "scopes": [left.scope_id, right.scope_id],
                            "locales": overlapping_locales,
                        }
                    )
            if (
                left.open_type_script == "DFLT"
                and right.inherits_default
                and overlapping_locales
            ) or (
                right.open_type_script == "DFLT"
                and left.inherits_default
                and overlapping_locales
            ):
                conflicts.append(
                    {
                        "kind": "default-scope-conflict",
                        "scopes": [left.scope_id, right.scope_id],
                        "locales": overlapping_locales,
                    }
                )
    return tuple(conflicts)


def merge_dictionaries(
    layers: Sequence[Iterable[DictionaryEntry]],
    *,
    policy: DictionaryPolicy | None = None,
    deny: Iterable[str] = (),
) -> NormalizedDictionary:
    """Merge base-to-override layers and apply a deterministic deny list."""

    resolved_policy = policy or DictionaryPolicy()
    deny_set = {
        _normalize_text(
            value,
            preserve_outer_space=resolved_policy.preserve_outer_space,
        )
        for value in deny
    }
    merged: dict[str, tuple[int, DictionaryEntry]] = {}
    for layer_index, layer in enumerate(layers):
        for entry in layer:
            if entry.source in deny_set or entry.target in deny_set:
                continue
            existing = merged.get(entry.source)
            if existing is not None and existing[1].target != entry.target:
                old_target = existing[1].target
                reverse = merged.get(old_target)
                if reverse is not None and reverse[1].target == entry.source:
                    del merged[old_target]
            if existing is None or (entry.priority, layer_index) >= (
                existing[1].priority,
                existing[0],
            ):
                merged[entry.source] = (layer_index, entry)
    return normalize_dictionary(
        (entry for _, entry in merged.values()),
        policy=resolved_policy,
    )
