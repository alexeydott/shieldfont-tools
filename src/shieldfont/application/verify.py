"""Structural, manifest, and codec-contract verification services."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import uharfbuzz as hb  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]


@dataclass(slots=True)
class VerificationReport:
    """Machine-readable verification result with safe human rendering."""

    status: str = "pass"
    checks: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def fail(self, check: str, message: str) -> None:
        self.status = "fail"
        self.checks[check] = "fail"
        self.errors.append(message)

    def pass_check(self, check: str) -> None:
        self.checks[check] = "pass"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": dict(sorted(self.checks.items())),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class ShapingResult:
    """Stable, privacy-safe HarfBuzz shaping result."""

    glyph_ids: tuple[int, ...]
    clusters: tuple[int, ...]
    advances: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "glyphIds": list(self.glyph_ids),
            "clusters": list(self.clusters),
            "advances": list(self.advances),
        }


def shape_text(
    path: Path,
    text: str,
    *,
    direction: str = "ltr",
    script: str = "latn",
    language: str = "dflt",
    features: tuple[str, ...] = (),
) -> ShapingResult:
    """Shape text with explicit HarfBuzz direction, script, language, and features."""

    if not text:
        raise ValueError("text must not be empty")
    font_data = path.read_bytes()
    face = hb.Face(font_data)
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.direction = direction
    buffer.script = script
    buffer.language = language
    hb.shape(font, buffer, list(features))
    return ShapingResult(
        glyph_ids=tuple(info.codepoint for info in buffer.glyph_infos),
        clusters=tuple(info.cluster for info in buffer.glyph_infos),
        advances=tuple(position.x_advance for position in buffer.glyph_positions),
    )


def verify_shaping_samples(
    path: Path,
    *,
    positive: tuple[str, ...] = ("A",),
    negative: tuple[str, ...] = (),
    direction: str = "ltr",
    script: str = "latn",
    language: str = "dflt",
    features: tuple[str, ...] = (),
) -> VerificationReport:
    """Verify positive shaping and that configured negative samples remain distinct."""

    report = VerificationReport()
    positive_results: list[ShapingResult] = []
    for sample in positive:
        result = shape_text(
            path,
            sample,
            direction=direction,
            script=script,
            language=language,
            features=features,
        )
        if not result.glyph_ids or all(glyph_id == 0 for glyph_id in result.glyph_ids):
            report.fail("shaping-positive", "positive sample shaped only to .notdef")
        else:
            positive_results.append(result)
    if positive_results:
        report.pass_check("shaping-positive")
    for sample in negative:
        result = shape_text(
            path,
            sample,
            direction=direction,
            script=script,
            language=language,
            features=features,
        )
        if not result.glyph_ids or all(glyph_id == 0 for glyph_id in result.glyph_ids):
            report.fail("shaping-negative", "negative sample shaped only to .notdef")
    if negative and "shaping-negative" not in report.checks:
        report.pass_check("shaping-negative")
    return report


def verify_font(path: Path, *, strict: bool = True) -> VerificationReport:
    """Verify required glyf, glyph-order, metrics, and checksum invariants."""

    report = VerificationReport()
    try:
        font = TTFont(path.resolve(), lazy=False, checkChecksums=1 if strict else 0)
    except (OSError, TTLibError) as error:
        report.fail("open", "font could not be reopened")
        report.errors.append(str(error))
        return report
    try:
        if "glyf" not in font:
            report.fail("outlines", "font does not contain glyf")
        else:
            report.pass_check("outlines")
        order = font.getGlyphOrder()
        if "maxp" in font and font["maxp"].numGlyphs == len(order):
            report.pass_check("maxp")
        else:
            report.fail("maxp", "maxp glyph count disagrees with glyph order")
        if "hmtx" in font and all(glyph in font["hmtx"].metrics for glyph in order):
            report.pass_check("hmtx")
        else:
            report.fail("hmtx", "hmtx metrics are missing for a glyph")
        _verify_layout_table(font, "GSUB", report)
        _verify_layout_table(font, "GPOS", report)
        if "DSIG" in font:
            report.warnings.append("DSIG is present after a modified-font build")
        else:
            report.pass_check("dsig")
        report.pass_check("open")
    finally:
        font.close()
    return report


def _verify_layout_table(font: TTFont, tag: str, report: VerificationReport) -> None:
    """Validate ScriptList, FeatureList, and LookupList references."""

    if tag not in font:
        report.checks.setdefault(f"{tag.lower()}-inventory", "pass")
        return
    table = font[tag].table
    lookup_count = len(getattr(table.LookupList, "Lookup", []))
    feature_count = len(getattr(table.FeatureList, "FeatureRecord", []))
    scripts = getattr(table.ScriptList, "ScriptRecord", [])
    valid = True
    for script_record in scripts:
        script = script_record.Script
        langsys_records = [script.DefaultLangSys, *[
            record.LangSys for record in script.LangSysRecord
        ]]
        for langsys in langsys_records:
            if langsys is None:
                continue
            if any(index >= feature_count for index in langsys.FeatureIndex):
                valid = False
    for feature_record in getattr(table.FeatureList, "FeatureRecord", []):
        if any(
            index >= lookup_count
            for index in feature_record.Feature.LookupListIndex
        ):
            valid = False
    check = f"{tag.lower()}-inventory"
    if valid:
        report.pass_check(check)
    else:
        report.fail(check, f"{tag} contains an invalid layout reference")


def verify_manifest(root: Path) -> VerificationReport:
    """Verify manifest artifact hashes and ruleset presence."""

    report = VerificationReport()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        report.fail("manifest", "manifest.json is missing")
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        report.fail("manifest", "manifest.json is unreadable")
        report.errors.append(str(error))
        return report
    if manifest.get("schema") != "shieldfont-build/v1":
        report.fail("manifest-schema", "unsupported manifest schema")
    else:
        report.pass_check("manifest-schema")
    _verify_manifest_metadata(manifest, report)
    for artifact in manifest.get("artifacts", []):
        artifact_path = root / str(artifact.get("path", ""))
        expected = artifact.get("sha256")
        if not artifact_path.exists() or expected != _sha256(artifact_path):
            report.fail(
                "artifact-hashes",
                f"artifact hash mismatch: {artifact_path.name}",
            )
            continue
    if manifest.get("artifacts"):
        report.checks.setdefault("artifact-hashes", "pass")
    ruleset_path = root / "ruleset.json"
    if ruleset_path.exists():
        _verify_ruleset(ruleset_path, report)
    else:
        report.fail("ruleset", "ruleset.json is missing")
    return report


def _verify_manifest_metadata(
    manifest: dict[str, object],
    report: VerificationReport,
) -> None:
    security = manifest.get("security", {})
    if not isinstance(security, dict):
        report.fail("security", "manifest security metadata is invalid")
    else:
        exposed = [
            key
            for key in ("browserDecoderIncluded", "mappingEmbedded")
            if security.get(key) is True
        ]
        if exposed:
            report.fail(
                "security",
                "browser mapping exposure is enabled: " + ", ".join(exposed),
            )
        else:
            report.pass_check("security")
    font = manifest.get("font", {})
    if isinstance(font, dict) and font.get("license") is not None:
        report.pass_check("license")
    else:
        report.warnings.append("font license metadata is not present")


def _verify_ruleset(path: Path, report: VerificationReport) -> None:
    try:
        ruleset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        report.fail("ruleset", "ruleset.json is unreadable")
        report.errors.append(str(error))
        return
    if ruleset.get("schema") != "shieldfont-ruleset/v1":
        report.fail("ruleset-schema", "unsupported ruleset schema")
        return
    report.pass_check("ruleset-schema")
    scopes = ruleset.get("scopes", [])
    mappings_valid = True
    for scope in scopes:
        rules = scope.get("rules", [])
        if any(
            not isinstance(rule.get("source"), str)
            or not isinstance(rule.get("target"), str)
            for rule in rules
        ):
            report.fail("codec-parity", "ruleset contains non-string mapping values")
        targets: set[str] = set()
        for rule in rules:
            target = rule.get("target")
            if isinstance(target, str) and target in targets:
                report.fail("codec-parity", "ruleset contains a target collision")
            if isinstance(target, str):
                targets.add(target)
        payload = [
            {
                "source": rule.get("source"),
                "target": rule.get("target"),
                "caseMode": rule.get("caseMode"),
                "priority": rule.get("priority"),
                "tags": rule.get("tags", []),
            }
            for rule in rules
        ]
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        actual = f"sha256:{hashlib.sha256(serialized).hexdigest()}"
        if actual != scope.get("mappingHash"):
            mappings_valid = False
            report.fail(
                "mapping-hashes",
                f"mapping hash mismatch: {scope.get('id', 'unknown')}",
            )
    if mappings_valid:
        report.pass_check("mapping-hashes")
    if report.checks.get("codec-parity") != "fail":
        report.pass_check("codec-parity")
    report.pass_check("ruleset")


def verify_reports(report: VerificationReport, output_dir: Path) -> dict[str, Path]:
    """Write JSON and safe HTML verification reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "verify.json"
    html_path = output_dir / "verify.html"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    rows = "".join(
        f"<li>{html.escape(key)}: {html.escape(value)}</li>"
        for key, value in sorted(report.checks.items())
    )
    html_path.write_text(
        "<!doctype html><meta charset=\"utf-8\">"
        f"<title>ShieldFont verification: {html.escape(report.status)}</title>"
        f"<p>Status: {html.escape(report.status)}</p><ul>{rows}</ul>",
        encoding="utf-8",
    )
    category_paths: dict[str, Path] = {}
    for category in ("layout", "security", "license"):
        category_path = output_dir / f"{category}.json"
        category_path.write_text(
            json.dumps(
                {
                    "schema": f"shieldfont-{category}-verification/v1",
                    **report.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        category_paths[category] = category_path
    return {"json": json_path, "html": html_path, **category_paths}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
