"""Dictionary application services and deterministic artifact writers."""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable
from pathlib import Path

from shieldfont.domain.dictionary.models import (
    DictionaryEntry,
    DictionaryPolicy,
    MappingMode,
    NormalizedDictionary,
)
from shieldfont.domain.dictionary.validation import (
    merge_dictionaries,
    normalize_dictionary,
)
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.infrastructure.dictionary.csv_reader import read_csv_dictionary
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.dictionary.application")


def policy_from_options(
    *,
    mapping_mode: str = "involution",
    duplicate_policy: str = "error",
    target_collision_policy: str = "error",
    self_map_policy: str = "drop-with-warning",
) -> DictionaryPolicy:
    try:
        return DictionaryPolicy(
            mapping_mode=MappingMode(mapping_mode),
            duplicate_policy=duplicate_policy,
            target_collision_policy=target_collision_policy,
            self_map_policy=self_map_policy,
        )
    except ValueError as error:
        raise ShieldFontError(
            "Unsupported dictionary policy",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="dictionary.arguments",
            details={
                "mappingMode": mapping_mode,
                "duplicatePolicy": duplicate_policy,
                "targetCollisionPolicy": target_collision_policy,
                "selfMapPolicy": self_map_policy,
            },
        ) from error


def load_and_normalize(
    paths: Iterable[Path],
    *,
    policy: DictionaryPolicy,
) -> NormalizedDictionary:
    entries: list[DictionaryEntry] = []
    for path in paths:
        entries.extend(read_csv_dictionary(path))
    return normalize_dictionary(entries, policy=policy)


def load_and_merge(
    paths: Iterable[Path],
    *,
    policy: DictionaryPolicy,
    deny: Iterable[str] = (),
) -> NormalizedDictionary:
    layers = [read_csv_dictionary(path) for path in paths]
    return merge_dictionaries(layers, policy=policy, deny=deny)


def write_dictionary_artifacts(
    dictionary: NormalizedDictionary,
    *,
    output_dir: Path,
    stem: str,
) -> dict[str, Path]:
    """Write canonical CSV, mapping JSON, inverse JSON, and report."""

    maps_dir = output_dir / "maps"
    reports_dir = output_dir / "reports"
    maps_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_path = maps_dir / f"{stem}.csv"
    json_path = maps_dir / f"{stem}.json"
    inverse_path = maps_dir / f"{stem}.inverse.json"
    report_path = reports_dir / f"{stem}.dictionary.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["source", "target"])
        writer.writerows((entry.source, entry.target) for entry in dictionary.entries)
    mapping = {entry.source: entry.target for entry in dictionary.entries}
    json_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    inverse_path.write_text(
        json.dumps(
            dict(dictionary.inverse),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "entries": len(dictionary.entries),
                "warnings": list(dictionary.warnings),
                "mappingHash": dictionary.mapping_hash,
                "sources": [str(path) for path in dictionary.source_files],
                "inverseEntries": len(dictionary.inverse),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    log_event(
        LOGGER,
        logging.INFO,
        "Dictionary artifacts written",
        code="SF-DICT-WRITTEN",
        stage="dictionary.emit",
        details={"outputDir": str(output_dir), "mappingHash": dictionary.mapping_hash},
    )
    return {
        "csv": csv_path,
        "json": json_path,
        "inverse": inverse_path,
        "report": report_path,
    }
