from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from shieldfont.application.build import build_project
from shieldfont.domain.errors import ShieldFontError


def test_document_bound_build_publishes_deterministic_canonical_bundle(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).parents[2]
        / "deps"
        / "shieldfont"
        / "packages"
        / "font"
        / "optik-n.woff2"
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "schema": "shieldfont.mapping.v2",
                "profile": "versioned-groups",
                "seed": {"id": "fixture", "value": "private-seed"},
                "groups": [
                    {
                        "id": "fixture.noun",
                        "grammar": "noun",
                        "sources": [
                            {
                                "source": "alpha",
                                "aliases": ["bravo", "charlie"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "content.txt").write_text("alpha", encoding="utf-8")
    config = tmp_path / "shieldfont.yml"
    config.write_text(
        f"""
schema: shieldfont/v1
project:
  outputDir: dist
  reproducible: true
  sourceDateEpoch: 0
source:
  path: {source.as_posix()}
font:
  family: ShieldFontFixture
  outputFormats: [ttf, woff2]
scopes:
  - id: default
    dictionaries: [mapping.json]
mapping:
  mode: directed
protection:
  profile: document-bound
  mappingContract: shieldfont.mapping.v2
  documentNonce: private-document
  inventory: [content.txt]
  scanPublicArtifacts: true
verification:
  levels: []
""",
        encoding="utf-8",
    )

    output = build_project(config)
    first_parent = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    first_canonical = json.loads(
        (output / "artifacts/build-manifest.json").read_text(encoding="utf-8")
    )
    ruleset = json.loads(
        (output / "artifacts/private/ruleset.json").read_text(encoding="utf-8")
    )
    output = build_project(config)
    second_parent = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    second_canonical = json.loads(
        (output / "artifacts/build-manifest.json").read_text(encoding="utf-8")
    )

    assert first_parent["buildId"] == second_parent["buildId"]
    assert first_canonical == second_canonical
    assert ruleset["mappingContract"]["schema"] == "shieldfont.mapping.v2"
    assert first_parent["profile"]["cacheIdentity"] == first_canonical["bundleId"]
    assert first_parent["security"]["publicArtifactScan"] == "pass"
    assert first_parent["security"]["glyphNamesDroppedFromWoff2"] is True
    assert (output / "artifacts/public/font-web.woff2").is_file()
    assert (output / "artifacts/private/font-audit.ttf").is_file()
    assert not (output / "ruleset.json").exists()
    assert not list((output / "features").glob("*.layout.json"))
    public_mapping = (output / "artifacts/public/mapping.json").read_text(
        encoding="utf-8"
    )
    assert "alpha" not in public_mapping
    assert "bravo" not in public_mapping
    public_css = (output / "artifacts/public/shieldfont.css").read_text(
        encoding="utf-8"
    )
    referenced_fonts = re.findall(r"url\(['\"]?([^'\")]+)", public_css)
    assert referenced_fonts
    assert all(
        (output / "artifacts/public" / reference).is_file()
        for reference in referenced_fonts
    )
    serialized = json.dumps(first_canonical, sort_keys=True)
    assert "private-document" not in serialized
    assert "private-seed" not in serialized
    assert "fixture.noun" not in serialized

    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "ShieldFontFixture",
            "ShieldFontFixtureChanged",
        ),
        encoding="utf-8",
    )
    changed_output = build_project(config)
    changed_manifest = json.loads(
        (changed_output / "artifacts/build-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert changed_manifest["bundleId"] != first_canonical["bundleId"]


def test_failed_public_scan_preserves_previous_atomic_publication(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).parents[2]
        / "deps"
        / "shieldfont"
        / "packages"
        / "font"
        / "optik-n.woff2"
    )
    (tmp_path / "mapping.json").write_text(
        json.dumps(
            {
                "schema": "shieldfont.mapping.v2",
                "groups": [
                    {
                        "id": "fixture.noun",
                        "grammar": "noun",
                        "sources": [
                            {"source": "alpha", "aliases": ["bravo", "charlie"]}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "content.txt").write_text("alpha", encoding="utf-8")
    destination = tmp_path / "dist"
    destination.mkdir()
    (destination / "previous.txt").write_text("keep", encoding="utf-8")
    config = tmp_path / "shieldfont.yml"
    config.write_text(
        f"""
schema: shieldfont/v1
project:
  outputDir: dist
  reproducible: true
source:
  path: {source.as_posix()}
font:
  family: Alpha
  outputFormats: [ttf, woff2]
scopes:
  - id: default
    dictionaries: [mapping.json]
mapping:
  mode: directed
protection:
  profile: document-bound
  mappingContract: shieldfont.mapping.v2
  inventory: [content.txt]
  scanPublicArtifacts: true
verification:
  levels: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ShieldFontError, match="privacy scan failed"):
        build_project(config)

    assert (destination / "previous.txt").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".dist.*"))
