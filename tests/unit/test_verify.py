from __future__ import annotations

import hashlib
import json
from pathlib import Path

from shieldfont.application.verify import verify_manifest, verify_reports


def test_manifest_verification_checks_artifact_hashes_and_writes_safe_reports(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ruleset.json"
    artifact.write_text('{"schema":"shieldfont-ruleset/v1"}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "shieldfont-build/v1",
                "artifacts": [{"path": "ruleset.json", "sha256": f"sha256:{digest}"}],
            }
        ),
        encoding="utf-8",
    )

    report = verify_manifest(tmp_path)
    outputs = verify_reports(report, tmp_path / "reports")

    assert report.status == "pass"
    assert outputs["json"].exists()
    assert "ruleset.json" not in outputs["html"].read_text(encoding="utf-8")


def test_manifest_verification_fails_closed_on_stale_artifact_hash(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ruleset.json"
    artifact.write_text("changed\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "shieldfont-build/v1",
                "artifacts": [{"path": "ruleset.json", "sha256": "sha256:stale"}],
            }
        ),
        encoding="utf-8",
    )

    report = verify_manifest(tmp_path)

    assert report.status == "fail"
    assert "artifact hash mismatch: ruleset.json" in report.errors
