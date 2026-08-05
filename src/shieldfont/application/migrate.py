"""Migration helpers for legacy flat ShieldFont projects."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml


def migrate_legacy_project(
    *,
    mapping_path: Path,
    font_path: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Convert a legacy flat mapping into a scoped project atomically."""

    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping_id, pairs, incompatibilities = _read_legacy_mapping(payload)
    if not font_path.exists():
        incompatibilities.append("source font does not exist")
    if not pairs:
        incompatibilities.append("legacy mapping contains no valid pairs")

    parent = output_dir.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
    published = False
    try:
        dictionaries = temporary / "dictionaries"
        dictionaries.mkdir()
        csv_path = dictionaries / "default.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("source", "target"))
            writer.writerows(pairs)
        config_path = temporary / "shieldfont.yml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "schema": "shieldfont/v1",
                    "project": {
                        "id": f"legacy-{mapping_id}",
                        "version": "0.1.0",
                    },
                    "source": {"path": os.fspath(font_path)},
                    "scopes": [
                        {
                            "id": "legacy-default",
                            "encoder": {"locales": [], "sourceScripts": ["Latn"]},
                            "shaping": {
                                "targetScripts": ["Latn"],
                                "openTypeScript": "latn",
                                "defaultLanguage": True,
                                "languages": [],
                            },
                            "dictionaries": ["dictionaries/default.csv"],
                        }
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        report_path = temporary / "migration-report.json"
        report_path.write_text(
            json.dumps(
                {
                    "schema": "shieldfont-migration/v1",
                    "mappingId": mapping_id,
                    "sourceFont": os.fspath(font_path),
                    "pairs": len(pairs),
                    "incompatibilities": incompatibilities,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary.rename(output_dir)
        published = True
        return {
            "config": output_dir / "shieldfont.yml",
            "dictionary": output_dir / "dictionaries" / "default.csv",
            "report": output_dir / "migration-report.json",
        }
    finally:
        if not published and temporary.exists():
            shutil.rmtree(temporary)


def _read_legacy_mapping(
    payload: Any,
) -> tuple[str, list[tuple[str, str]], list[str]]:
    incompatibilities: list[str] = []
    if not isinstance(payload, dict):
        return "", [], ["legacy mapping root must be an object"]
    metadata = payload.get("metadata")
    source = payload.get("mapping", payload)
    if not isinstance(source, dict):
        return "", [], ["legacy mapping must be a flat object"]
    pairs: list[tuple[str, str]] = []
    for key, value in source.items():
        if key in {"id", "mappingId", "metadata", "mapping"} and source is payload:
            continue
        if not isinstance(key, str) or not isinstance(value, str):
            incompatibilities.append(f"non-string mapping pair: {key!r}")
            continue
        pairs.append((key, value))
    mapping_id = ""
    if isinstance(metadata, dict):
        mapping_id = str(metadata.get("mappingId", ""))
    mapping_id = str(payload.get("mappingId", payload.get("id", mapping_id)))
    if not mapping_id:
        serialized = json.dumps(
            sorted(pairs), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        mapping_id = f"legacy-{hashlib.sha256(serialized).hexdigest()[:16]}"
    return mapping_id, sorted(pairs), incompatibilities
