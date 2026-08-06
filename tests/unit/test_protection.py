from __future__ import annotations

import json
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from pydantic import ValidationError

from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.errors import ShieldFontError
from shieldfont.domain.protection import (
    derive_bundle_id,
    select_versioned_mapping,
)
from shieldfont.infrastructure.artifacts import (
    emit_canonical_artifacts,
    scan_public_artifacts,
)
from shieldfont.infrastructure.font.compile import gsub_optimization_diagnostics


def _contract() -> dict[str, object]:
    return {
        "schema": "shieldfont.mapping.v2",
        "profile": "versioned-groups",
        "seed": {"id": "fixture-seed", "value": "fixture-private-value"},
        "groups": [
            {
                "id": "fixture.noun",
                "grammar": "noun",
                "sources": [
                    {
                        "source": "alpha",
                        "aliases": ["bravo", "charlie", "delta"],
                    }
                ],
            },
            {
                "id": "fixture.verb",
                "grammar": "verb",
                "sources": [
                    {
                        "source": "echo",
                        "aliases": ["foxtrot", "golf", "hotel"],
                    }
                ],
            },
        ],
    }


def _mapping(selection: object) -> dict[str, str]:
    return {
        entry.source: entry.target
        for entry in selection.entries  # type: ignore[attr-defined]
    }


def test_versioned_mapping_replays_without_exposing_private_inputs() -> None:
    first = select_versioned_mapping(_contract(), nonce="document-a")
    replay = select_versioned_mapping(_contract(), nonce="document-a")
    alternatives = [
        select_versioned_mapping(_contract(), nonce=f"document-{index}")
        for index in range(20)
    ]

    assert _mapping(first) == _mapping(replay)
    assert any(_mapping(candidate) != _mapping(first) for candidate in alternatives)
    serialized = json.dumps(first.metadata, sort_keys=True)
    assert "document-a" not in serialized
    assert "fixture-private-value" not in serialized
    assert first.metadata["nonce"]["digestPrefix"]  # type: ignore[index]


def test_versioned_mapping_rejects_alias_reuse_across_groups() -> None:
    contract = _contract()
    groups = contract["groups"]
    groups[1]["sources"][0]["aliases"][0] = "bravo"  # type: ignore[index]

    with pytest.raises(ShieldFontError, match="reused across groups"):
        select_versioned_mapping(contract)


def test_document_subset_keeps_required_group_and_bounded_reserve() -> None:
    selected = select_versioned_mapping(
        _contract(),
        inventory={"alpha": 1},
        document_bound=True,
        reserve_aliases=1,
    )
    mapping = _mapping(selected)

    assert "alpha" in mapping
    assert "echo" in mapping
    assert selected.metadata["selectedGroupCount"] == 2
    with pytest.raises(ShieldFontError, match="exceed available"):
        select_versioned_mapping(
            _contract(),
            inventory={},
            document_bound=True,
            reserve_aliases=3,
        )


def test_protection_profile_rejects_incoherent_options() -> None:
    with pytest.raises(ValidationError, match="require shieldfont.mapping.v2"):
        ShieldFontConfig.model_validate(
            {
                "schema": "shieldfont/v1",
                "protection": {"documentNonce": "private"},
            }
        )
    with pytest.raises(ValidationError, match="requires reproducible builds"):
        ShieldFontConfig.model_validate(
            {
                "schema": "shieldfont/v1",
                "project": {"reproducible": False},
                "protection": {
                    "profile": "document-bound",
                    "mappingContract": "shieldfont.mapping.v2",
                },
            }
        )
    with pytest.raises(ValidationError, match="requires scanPublicArtifacts"):
        ShieldFontConfig.model_validate(
            {
                "schema": "shieldfont/v1",
                "protection": {
                    "profile": "document-bound",
                    "mappingContract": "shieldfont.mapping.v2",
                },
            }
        )


def test_bundle_identity_changes_for_nonce_inventory_and_compatibility() -> None:
    base = derive_bundle_id(
        inventory={"alpha": 1},
        mapping_hash="sha256:mapping",
        font_hash="sha256:font",
        nonce="nonce-a",
        tenant_id="tenant-a",
        compatibility={"reserve": 1},
    )

    assert base != derive_bundle_id(
        inventory={"alpha": 1},
        mapping_hash="sha256:mapping",
        font_hash="sha256:font",
        nonce="nonce-b",
        tenant_id="tenant-a",
        compatibility={"reserve": 1},
    )
    assert base != derive_bundle_id(
        inventory={"alpha": 2},
        mapping_hash="sha256:mapping",
        font_hash="sha256:font",
        nonce="nonce-a",
        tenant_id="tenant-a",
        compatibility={"reserve": 1},
    )
    assert len(base) == 24


def test_public_scanner_rejects_private_and_unstable_metadata(tmp_path: Path) -> None:
    (tmp_path / "mapping.audit.json").write_text("{}", encoding="utf-8")
    (tmp_path / "metadata.txt").write_text(
        "built 2026-08-06 at C:\\build\\font.ttf",
        encoding="utf-8",
    )

    report = scan_public_artifacts(tmp_path)
    kinds = {finding["kind"] for finding in report["findings"]}

    assert report["status"] == "fail"
    assert {"private-artifact", "absolute-path", "timestamp"} <= kinds


def test_public_scanner_does_not_exempt_raw_mapping_pairs(tmp_path: Path) -> None:
    (tmp_path / "mapping.json").write_text(
        '{"alpha":"bravo"}\n',
        encoding="utf-8",
    )

    report = scan_public_artifacts(
        tmp_path,
        forbidden_words=("alpha", "bravo"),
    )

    assert report["status"] == "fail"
    assert report["findings"] == [
        {"file": "mapping.json", "kind": "mapping-hint"}
    ]


def test_canonical_artifacts_have_explicit_roles_and_web_post_format3(
    tmp_path: Path,
) -> None:
    upstream_font = (
        Path(__file__).parents[2]
        / "deps"
        / "shieldfont"
        / "packages"
        / "font"
        / "optik-n.woff2"
    )
    audit_font = tmp_path / "audit.ttf"
    font = TTFont(upstream_font, lazy=False)
    font.flavor = None
    font.save(audit_font)
    font.close()
    css = tmp_path / "shieldfont.css"
    css.write_text(".sf-shield { font-family: ShieldFont; }\n", encoding="utf-8")
    ruleset = tmp_path / "ruleset.json"
    ruleset.write_text('{"schema":"shieldfont-ruleset/v1"}\n', encoding="utf-8")

    manifest = emit_canonical_artifacts(
        tmp_path / "artifacts",
        mappings={"default": {"alpha": "bravo", "bravo": "alpha"}},
        audit_font=audit_font,
        web_font=upstream_font,
        css=css,
        ruleset=ruleset,
        bundle_id="0123456789abcdef01234567",
        mapping_contract={
            "schema": "shieldfont.mapping.v2",
            "nonce": {"source": "provided", "digestPrefix": "0123456789ab"},
        },
        source_date_epoch=0,
        scan_public=True,
    )

    assert {item["privacy"] for item in manifest["artifacts"]} == {
        "public",
        "private",
        "verification",
    }
    assert manifest["cacheIdentity"] == manifest["bundleId"]
    web_font = TTFont(
        tmp_path / "artifacts" / "public" / "font-web.woff2",
        lazy=False,
    )
    assert float(web_font["post"].formatType) == 3.0
    web_font.close()
    assert not (
        tmp_path / "artifacts" / "public" / "mapping.audit.json"
    ).exists()
    public_mapping = (
        tmp_path / "artifacts" / "public" / "mapping.json"
    ).read_text(encoding="utf-8")
    private_mapping = (
        tmp_path / "artifacts" / "private" / "mapping.json"
    ).read_text(encoding="utf-8")
    assert "alpha" not in public_mapping
    assert "bravo" not in public_mapping
    assert "alpha" in private_mapping


def test_gsub_format2_request_reports_deterministic_format3_fallback() -> None:
    diagnostics = gsub_optimization_diagnostics(
        boundary_glyphs=12000,
        substituted_glyphs=30000,
        optimization="format2",
    )

    assert diagnostics["selected"] == "format3"
    assert diagnostics["fallback"] == "shaping-validation-required"
    assert diagnostics["format2EstimatedBytes"] < diagnostics[
        "format3EstimatedBytes"
    ]
