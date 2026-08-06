"""Pure contracts for versioned mappings and document-bound identities."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from shieldfont.domain.dictionary.models import CaseMode, DictionaryEntry
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError

MAPPING_V2_SCHEMA = "shieldfont.mapping.v2"
MAPPING_V2_PROFILE = "versioned-groups"
PUBLIC_MAPPING_SCHEMA = "shieldfont.mapping.metadata.v1"
PRIVATE_ENCODER_SCHEMA = "shieldfont.mapping.private.v1"
PRIVATE_MAPPING_SCHEMA = "shieldfont.mapping.audit.v1"
BUILD_MANIFEST_SCHEMA = "shieldfont.build-manifest.v1"
PUBLIC_SCAN_SCHEMA = "shieldfont.public-scan.v1"
_GRAMMAR_BUCKET = re.compile(
    r"^(?:adj|adv|legacy|noun|other|special|verb)"
    r"(?:\.[A-Za-z0-9_-]+)*$",
    re.IGNORECASE,
)


def _contract_error(message: str, **details: object) -> ShieldFontError:
    return ShieldFontError(
        message,
        code=ErrorCode.DICTIONARY_PARSE,
        exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
        stage="mapping.contract",
        details=details,
    )


def canonical_json(value: object) -> str:
    """Serialize an identity input independently of dictionary order."""

    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def safe_digest(value: object, *, length: int = 16) -> str:
    """Return an opaque bounded digest for identities and diagnostics."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def inventory_digest(inventory: Mapping[str, int] | Iterable[str]) -> str:
    """Hash normalized inventory words and counts."""

    return safe_digest(_inventory_items(inventory))


def _inventory_items(
    inventory: Mapping[str, int] | Iterable[str],
) -> list[tuple[str, int]]:
    if isinstance(inventory, Mapping):
        counts = {
            str(word).casefold(): int(count)
            for word, count in inventory.items()
            if int(count) > 0
        }
    else:
        counts = dict(Counter(str(word).casefold() for word in inventory))
    return sorted(counts.items())


def nonce_metadata(nonce: str | None) -> dict[str, str]:
    """Return safe nonce metadata without returning the nonce."""

    if nonce is None or not nonce:
        return {"source": "none", "digestPrefix": ""}
    return {
        "source": "provided",
        "digestPrefix": hashlib.sha256(nonce.encode("utf-8")).hexdigest()[:12],
    }


def derive_bundle_id(
    *,
    inventory: Mapping[str, int] | Iterable[str],
    mapping_hash: str,
    font_hash: str,
    nonce: str | None = None,
    tenant_id: str | None = None,
    compatibility: Mapping[str, object] | None = None,
    length: int = 24,
) -> str:
    """Derive an opaque identity from every bundle-affecting input."""

    payload = {
        "protocol": "shieldfont.bundle.v1",
        "inventoryDigest": safe_digest(_inventory_items(inventory), length=64),
        "mappingHash": mapping_hash,
        "fontHash": font_hash,
        "nonceDigest": (
            hashlib.sha256(nonce.encode("utf-8")).hexdigest() if nonce else ""
        ),
        "tenantDigest": safe_digest(tenant_id, length=64) if tenant_id else "",
        "compatibility": dict(compatibility or {}),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[
        :length
    ]


@dataclass(frozen=True, slots=True)
class MappingContractSelection:
    """Selected flat entries plus safe versioned-contract metadata."""

    entries: tuple[DictionaryEntry, ...]
    metadata: Mapping[str, object]


class _RuleLike(Protocol):
    @property
    def source(self) -> str: ...

    @property
    def target(self) -> str: ...


class _ScopeLike(Protocol):
    @property
    def scope_id(self) -> str: ...

    @property
    def rules(self) -> Sequence[_RuleLike]: ...


def _ordered_strings(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _contract_error(f"{label} must be a non-empty ordered list")
    result: list[str] = []
    positions: list[int] = []
    for index, item in enumerate(value):
        raw = item
        position = None
        if isinstance(item, Mapping):
            raw = item.get("alias", item.get("value", item.get("text")))
            position = item.get("position")
        if not isinstance(raw, str) or not raw:
            raise _contract_error(f"{label}[{index}] must be a non-empty string")
        if position is not None:
            if not isinstance(position, int):
                raise _contract_error(f"{label} positions must be integers")
            positions.append(position)
        result.append(raw)
    if positions and positions != list(range(len(positions))):
        raise _contract_error(f"{label} positions changed ordering")
    if len(set(result)) != len(result):
        raise _contract_error(f"{label} reuses an alias")
    return tuple(result)


def _select_alias(
    *,
    group_id: str,
    source: str,
    aliases: Sequence[str],
    seed: str,
    nonce: str,
    used: set[str],
) -> str:
    candidates = [alias for alias in aliases if alias not in used]
    if not candidates:
        raise _contract_error("No unused alias remains", source=source)
    digest = hmac.new(
        seed.encode("utf-8"),
        f"{nonce}\0{group_id}\0{source}".encode(),
        hashlib.sha256,
    ).digest()
    return min(
        enumerate(candidates),
        key=lambda item: (
            hashlib.sha256(
                digest
                + str(item[0]).encode("ascii")
                + item[1].encode("utf-8")
            ).digest(),
            item[0],
        ),
    )[1]


def select_versioned_mapping(
    raw: object,
    *,
    seed_override: str | None = None,
    nonce: str | None = None,
    inventory: Mapping[str, int] | Iterable[str] = (),
    document_bound: bool = False,
    reserve_aliases: int = 0,
    reserve: Sequence[str] = (),
) -> MappingContractSelection:
    """Validate a grouped v2 contract and materialize its selected aliases."""

    if not isinstance(raw, Mapping):
        raise _contract_error("Versioned mapping must be a JSON object")
    if raw.get("schema") not in {MAPPING_V2_SCHEMA, 2}:
        raise _contract_error("Unsupported mapping schema", schema=raw.get("schema"))
    if raw.get("profile", MAPPING_V2_PROFILE) not in {
        MAPPING_V2_PROFILE,
        "groups",
        "versioned",
    }:
        raise _contract_error(
            "Unsupported mapping profile",
            profile=raw.get("profile"),
        )
    groups = raw.get("groups", raw.get("source_groups"))
    if not isinstance(groups, list) or not groups:
        raise _contract_error("Versioned mapping groups must be non-empty")

    raw_seed = raw.get("seed", raw.get("mapping_seed", "0"))
    explicit_seed_id = isinstance(raw_seed, Mapping) and raw_seed.get("id") is not None
    if isinstance(raw_seed, Mapping):
        seed_value = raw_seed.get("value", raw_seed.get("seed", raw_seed.get("id")))
        seed_id = raw_seed.get("id", seed_value)
    else:
        seed_value = raw_seed
        seed_id = raw_seed
    if seed_value is None:
        seed_value = "0"
    seed = seed_override if seed_override is not None else str(seed_value)
    safe_seed_id = (
        str(seed_id)[:64]
        if seed_override is None and explicit_seed_id
        else f"seed-{safe_digest(seed)}"
    )
    raw_nonce = raw.get("document_nonce", raw.get("nonce"))
    if nonce is None and isinstance(raw_nonce, Mapping):
        raw_nonce = raw_nonce.get(
            "value",
            raw_nonce.get("nonce", raw_nonce.get("document_nonce")),
        )
    if nonce is None and raw_nonce is not None:
        if not isinstance(raw_nonce, str) or not raw_nonce:
            raise _contract_error("Document nonce must be a non-empty string")
        nonce = raw_nonce
    inventory_words = {
        str(word).casefold()
        for word, count in (
            inventory.items()
            if isinstance(inventory, Mapping)
            else Counter(inventory).items()
        )
        if int(count) > 0
    }
    explicit_reserve = {value.casefold() for value in reserve}
    if reserve_aliases < 0:
        raise _contract_error("reserveAliases must not be negative")

    normalized_groups: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    seen_sources: set[str] = set()
    seen_alias_groups: dict[str, str] = {}
    known_words: set[str] = set()
    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise _contract_error("Each mapping group must be an object")
        group_id = group.get("id", group.get("group_id"))
        grammar = group.get(
            "grammar",
            group.get("grammar_bucket", group.get("bucket")),
        )
        if not isinstance(group_id, str) or not group_id:
            raise _contract_error("Mapping group id must be a non-empty string")
        if group_id in seen_groups:
            raise _contract_error("Mapping group ids must be unique", group=group_id)
        seen_groups.add(group_id)
        if not isinstance(grammar, str) or not _GRAMMAR_BUCKET.fullmatch(grammar):
            raise _contract_error("Invalid grammar bucket", group=group_id)
        sources = group.get("sources", group.get("entries"))
        if not isinstance(sources, list) or not sources:
            raise _contract_error("Mapping group sources must be non-empty")
        normalized_sources: list[dict[str, Any]] = []
        positions: list[int] = []
        for source_index, item in enumerate(sources):
            if not isinstance(item, Mapping):
                raise _contract_error("Mapping source entry must be an object")
            source = item.get("source", item.get("word"))
            if not isinstance(source, str) or not source:
                raise _contract_error("Mapping source must be a non-empty string")
            if source in seen_sources:
                raise _contract_error("Source is reused across groups", source=source)
            seen_sources.add(source)
            position = item.get("position")
            if position is not None:
                if not isinstance(position, int):
                    raise _contract_error("Source positions must be integers")
                positions.append(position)
            aliases = _ordered_strings(
                item.get("aliases", item.get("targets")),
                label=f"aliases for source {source!r}",
            )
            if source in aliases:
                raise _contract_error("Alias must differ from source", source=source)
            for alias in aliases:
                previous = seen_alias_groups.get(alias)
                if previous is not None and previous != group_id:
                    raise _contract_error(
                        "Alias is reused across groups",
                        alias=alias,
                    )
                seen_alias_groups[alias] = group_id
            known_words.update(
                [source.casefold(), *(alias.casefold() for alias in aliases)]
            )
            normalized_sources.append(
                {
                    "source": source,
                    "aliases": aliases,
                    "position": source_index,
                }
            )
        if positions and positions != list(range(len(positions))):
            raise _contract_error("Source positions changed ordering", group=group_id)
        normalized_groups.append(
            {
                "id": group_id,
                "version": str(group.get("version", "1")),
                "grammar": grammar,
                "position": group_index,
                "sources": normalized_sources,
            }
        )

    unknown_reserve = explicit_reserve - known_words
    if unknown_reserve:
        raise _contract_error(
            "Configured reserve entries are unavailable",
            count=len(unknown_reserve),
        )
    required_groups: set[str] = set()
    reserve_entries: list[tuple[str, Mapping[str, object]]] = []
    available_entries: list[tuple[str, Mapping[str, object]]] = []
    for group in normalized_groups:
        group_id = str(group["id"])
        group_words = {
            str(entry["source"]).casefold()
            for entry in group["sources"]
        }
        group_words.update(
            str(alias).casefold()
            for entry in group["sources"]
            for alias in entry["aliases"]
        )
        if not document_bound or inventory_words.intersection(group_words):
            required_groups.add(group_id)
            continue
        for entry in group["sources"]:
            entry_words = {
                str(entry["source"]).casefold(),
                *(str(alias).casefold() for alias in entry["aliases"]),
            }
            pair = (group_id, entry)
            if explicit_reserve.intersection(entry_words):
                reserve_entries.append(pair)
            else:
                available_entries.append(pair)
    if reserve_aliases > len(available_entries):
        raise _contract_error(
            "Requested reserve aliases exceed available entries",
            requested=reserve_aliases,
            available=len(available_entries),
        )
    reserve_entries.extend(available_entries[:reserve_aliases])
    reserve_keys = {
        (group_id, str(entry["source"])) for group_id, entry in reserve_entries
    }

    selected_pairs: list[tuple[str, str, tuple[str, ...]]] = []
    used_aliases: set[str] = set()
    kept_groups: list[str] = []
    for group in normalized_groups:
        group_id = str(group["id"])
        selected_sources = [
            entry
            for entry in group["sources"]
            if group_id in required_groups
            or (group_id, str(entry["source"])) in reserve_keys
        ]
        if not selected_sources:
            continue
        kept_groups.append(group_id)
        for entry in selected_sources:
            source = str(entry["source"])
            alias = _select_alias(
                group_id=group_id,
                source=source,
                aliases=entry["aliases"],
                seed=seed,
                nonce=nonce or "",
                used=used_aliases,
            )
            used_aliases.add(alias)
            entry_tags = (
                f"group:{group_id}",
                f"grammar:{group['grammar']}",
                f"contract:{MAPPING_V2_SCHEMA}",
            )
            selected_pairs.append((source, alias, entry_tags))

    selected_map = {source: alias for source, alias, _ in selected_pairs}
    for source, alias, _ in selected_pairs:
        if alias in selected_map and selected_map[alias] != source:
            raise _contract_error(
                "Selected alias conflicts with another source",
                alias=alias,
            )
    selected_entries: list[DictionaryEntry] = []
    for source, alias, pair_tags in selected_pairs:
        selected_entries.extend(
            (
                DictionaryEntry(
                    source,
                    alias,
                    case_mode=CaseMode.AUTO,
                    tags=pair_tags,
                ),
                DictionaryEntry(
                    alias,
                    source,
                    case_mode=CaseMode.AUTO,
                    tags=pair_tags,
                ),
            )
        )

    metadata: dict[str, object] = {
        "schema": MAPPING_V2_SCHEMA,
        "profile": MAPPING_V2_PROFILE,
        "seedId": safe_seed_id,
        "nonce": nonce_metadata(nonce),
        "groupCount": len(normalized_groups),
        "selectedGroupCount": len(kept_groups),
        "selectedGroupDigests": [safe_digest(group_id) for group_id in kept_groups],
        "inventoryDigest": inventory_digest(inventory),
        "inventoryCount": len(inventory_words),
        "reserveRequested": len(explicit_reserve) + reserve_aliases,
        "reserveSelected": len(reserve_entries),
    }
    return MappingContractSelection(tuple(selected_entries), metadata)


def mapping_by_scope(
    scopes: Sequence[_ScopeLike],
) -> dict[str, dict[str, str]]:
    """Extract source-target mappings from scope-like ruleset records."""

    result: dict[str, dict[str, str]] = {}
    for scope in scopes:
        scope_id = str(scope.scope_id)
        rules = scope.rules
        result[scope_id] = {
            str(rule.source): str(rule.target)
            for rule in rules
        }
    return result
