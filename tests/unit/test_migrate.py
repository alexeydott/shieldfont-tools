from __future__ import annotations

import json
from pathlib import Path

from shieldfont.application.migrate import migrate_legacy_project
from shieldfont.config.loader import load_config


def test_legacy_migration_writes_scoped_project_and_preserves_mapping_id(
    tmp_path: Path,
) -> None:
    mapping = tmp_path / "legacy.json"
    mapping.write_text(
        json.dumps({"mappingId": "v18", "A": "B", "C": "D"}),
        encoding="utf-8",
    )
    output = tmp_path / "migrated"

    artifacts = migrate_legacy_project(
        mapping_path=mapping,
        font_path=tmp_path / "Source.ttf",
        output_dir=output,
    )

    assert artifacts["config"].exists()
    assert "source,target\nA,B\nC,D\n" in artifacts["dictionary"].read_text(
        encoding="utf-8-sig"
    )
    report = json.loads(artifacts["report"].read_text(encoding="utf-8"))
    assert report["mappingId"] == "v18"
    assert "source font does not exist" in report["incompatibilities"]
    assert load_config(artifacts["config"]).project.id == "legacy-v18"
