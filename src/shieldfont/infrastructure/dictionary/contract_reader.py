"""Filesystem adapters for versioned mapping and document inventory contracts."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

from shieldfont.domain.dictionary.models import DictionaryEntry
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.protection import (
    MappingContractSelection,
    select_versioned_mapping,
)
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.dictionary.contract")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def read_document_inventory(paths: list[Path]) -> Counter[str]:
    """Read UTF-8 build inputs into a normalized word-count inventory."""

    counts: Counter[str] = Counter()
    for path in paths:
        source = path.resolve()
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as error:
            raise ShieldFontError(
                "Unable to read document inventory input",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="protection.inventory",
                details={"file": source.name, "reason": str(error)},
            ) from error
        normalized = unicodedata.normalize("NFC", text)
        counts.update(
            match.group(0).casefold()
            for match in _WORD_RE.finditer(normalized)
        )
    log_event(
        LOGGER,
        logging.INFO,
        "Document inventory analyzed",
        code="SF-PROTECTION-INVENTORY",
        stage="protection.inventory",
        details={
            "inputs": len(paths),
            "words": len(counts),
            "tokens": sum(counts.values()),
        },
    )
    return counts


def read_versioned_mapping(
    path: Path,
    *,
    seed_override: str | None,
    nonce: str | None,
    inventory: Counter[str],
    document_bound: bool,
    reserve_aliases: int,
    reserve: list[str],
) -> MappingContractSelection:
    """Read and select a ``shieldfont.mapping.v2`` JSON contract."""

    source = path.resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ShieldFontError(
            "Unable to read versioned mapping contract",
            code=ErrorCode.DICTIONARY_PARSE,
            exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
            stage="mapping.contract",
            details={"file": source.name, "reason": str(error)},
        ) from error
    selection = select_versioned_mapping(
        raw,
        seed_override=seed_override,
        nonce=nonce,
        inventory=inventory,
        document_bound=document_bound,
        reserve_aliases=reserve_aliases,
        reserve=reserve,
    )
    entries = tuple(
        DictionaryEntry(
            source=entry.source,
            target=entry.target,
            enabled=entry.enabled,
            case_mode=entry.case_mode,
            priority=entry.priority,
            tags=entry.tags,
            comment=entry.comment,
            origin_file=source,
        )
        for entry in selection.entries
    )
    return MappingContractSelection(entries, selection.metadata)
