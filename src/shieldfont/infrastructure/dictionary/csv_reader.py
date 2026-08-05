"""UTF-8 CSV dictionary reader with legacy header aliases."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from shieldfont.domain.dictionary.models import CaseMode, DictionaryEntry
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.dictionary.csv")
_REQUIRED_HEADERS = {"source", "target"}
_ALIASES = {"key": "source", "value": "target"}
_KNOWN_HEADERS = {
    "source",
    "target",
    "key",
    "value",
    "enabled",
    "case_mode",
    "priority",
    "tags",
    "comment",
}


def _parse_bool(value: str, *, path: Path, line: int) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ShieldFontError(
        "Dictionary enabled must be a boolean",
        code=ErrorCode.DICTIONARY_PARSE,
        exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
        stage="dictionary.read",
        details={"file": str(path), "line": line, "value": value},
    )


def read_csv_dictionary(path: Path) -> list[DictionaryEntry]:
    """Read a UTF-8/BOM CSV into entries carrying file and line provenance."""

    source_path = path.resolve()
    log_event(
        LOGGER,
        logging.DEBUG,
        "Reading dictionary CSV",
        code="SF-DICT-READ",
        stage="dictionary.read",
        details={"file": str(source_path)},
    )
    try:
        handle = source_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise ShieldFontError(
            "Unable to open dictionary CSV",
            code=ErrorCode.DICTIONARY_PARSE,
            exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
            stage="dictionary.read",
            details={"file": str(source_path), "reason": str(error)},
        ) from error
    with handle:
        reader = csv.DictReader(handle)
        raw_headers = reader.fieldnames or []
        headers = [
            _ALIASES.get(header.strip(), header.strip()) for header in raw_headers
        ]
        if len(headers) != len(set(headers)):
            raise ShieldFontError(
                "Dictionary CSV contains duplicate headers",
                code=ErrorCode.DICTIONARY_PARSE,
                exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                stage="dictionary.read",
                details={"file": str(source_path), "headers": raw_headers},
            )
        if not _REQUIRED_HEADERS.issubset(headers):
            raise ShieldFontError(
                "Dictionary CSV must contain source and target headers",
                code=ErrorCode.DICTIONARY_PARSE,
                exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                stage="dictionary.read",
                details={"file": str(source_path), "headers": raw_headers},
            )
        unknown = sorted(set(headers) - _KNOWN_HEADERS)
        if unknown:
            raise ShieldFontError(
                "Dictionary CSV contains unknown headers",
                code=ErrorCode.DICTIONARY_PARSE,
                exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                stage="dictionary.read",
                details={"file": str(source_path), "headers": unknown},
            )
        entries: list[DictionaryEntry] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ShieldFontError(
                    "Dictionary CSV row contains more fields than its header",
                    code=ErrorCode.DICTIONARY_PARSE,
                    exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                    stage="dictionary.read",
                    details={"file": str(source_path), "line": line_number},
                )
            normalized_row = {
                _ALIASES.get(key.strip(), key.strip()): (value or "")
                for key, value in row.items()
                if key is not None
            }
            try:
                case_mode = CaseMode(normalized_row.get("case_mode", "auto") or "auto")
                priority = int(normalized_row.get("priority", "0") or "0")
            except (ValueError, TypeError) as error:
                raise ShieldFontError(
                    "Dictionary case_mode or priority is invalid",
                    code=ErrorCode.DICTIONARY_PARSE,
                    exit_code=ExitCode.DICTIONARY_PARSE_ERROR,
                    stage="dictionary.read",
                    details={"file": str(source_path), "line": line_number},
                ) from error
            entries.append(
                DictionaryEntry(
                    source=normalized_row.get("source", ""),
                    target=normalized_row.get("target", ""),
                    enabled=_parse_bool(
                        normalized_row.get("enabled", ""),
                        path=source_path,
                        line=line_number,
                    ),
                    case_mode=case_mode,
                    priority=priority,
                    tags=tuple(
                        tag.strip()
                        for tag in normalized_row.get("tags", "").split(";")
                        if tag.strip()
                    ),
                    comment=normalized_row.get("comment", ""),
                    origin_file=source_path,
                    origin_line=line_number,
                )
            )
    log_event(
        LOGGER,
        logging.INFO,
        "Dictionary CSV read",
        code="SF-DICT-READ-COMPLETE",
        stage="dictionary.read",
        details={"file": str(source_path), "entries": len(entries)},
    )
    return entries
