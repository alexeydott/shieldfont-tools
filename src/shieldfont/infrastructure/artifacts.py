"""Canonical public/private artifact publication and privacy scanning."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.protection import (
    BUILD_MANIFEST_SCHEMA,
    PRIVATE_ENCODER_SCHEMA,
    PRIVATE_MAPPING_SCHEMA,
    PUBLIC_MAPPING_SCHEMA,
    PUBLIC_SCAN_SCHEMA,
)

_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|tmp|var|private|workspace)/)"
)
_TIMESTAMP = re.compile(
    r"\b20\d{2}-\d{2}-\d{2}(?:[T ][0-9]{2}:[0-9]{2}:[0-9]{2})?\b"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _record(path: Path, *, root: Path, schema: str, privacy: str) -> dict[str, object]:
    return {
        "name": path.name,
        "schema": schema,
        "privacy": privacy,
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def apply_reproducible_font_metadata(font: TTFont, epoch: int) -> None:
    """Set controlled OpenType timestamps and disable save-time refresh."""

    if "head" not in font:
        return
    opentype_epoch = 2082844800 + epoch
    font["head"].created = opentype_epoch
    font["head"].modified = opentype_epoch
    font.recalcTimestamp = False


def _write_web_font(source: Path, destination: Path, *, epoch: int) -> Path:
    font = TTFont(source, lazy=False)
    try:
        if "glyf" not in font:
            raise ShieldFontError(
                "Canonical web artifacts require TrueType glyf outlines",
                code=ErrorCode.FONT_UNSUPPORTED,
                exit_code=ExitCode.UNSUPPORTED_FONT,
                stage="artifacts.canonical",
            )
        post = font.get("post")
        if post is not None:
            post.formatType = 3.0
            post.glyphOrder = []
            post.extraNames = []
            post.mapping = {}
        apply_reproducible_font_metadata(font, epoch)
        destination.parent.mkdir(parents=True, exist_ok=True)
        font.flavor = "woff2"
        font.save(destination)
    finally:
        font.close()
    return destination


def scan_public_artifacts(
    root: Path,
    *,
    forbidden_words: Iterable[str] = (),
    excluded_names: Iterable[str] = (),
) -> dict[str, object]:
    """Scan the public tier for private artifacts and unstable metadata."""

    excluded = set(excluded_names)
    forbidden = {
        word
        for word in (str(value) for value in forbidden_words)
        if len(word) >= 3
    }
    findings: list[dict[str, str]] = []
    files = sorted(path for path in root.rglob("*") if path.is_file())
    private_names = {
        "mapping.audit.json",
        "mapping.audit.csv",
        "font-audit.ttf",
    }
    for path in files:
        if path.name in excluded:
            continue
        relative = path.relative_to(root).as_posix()
        if path.name in private_names:
            findings.append({"file": relative, "kind": "private-artifact"})
            continue
        if path.suffix.lower() in {".ttf", ".woff", ".woff2"}:
            try:
                font = TTFont(path, lazy=False)
                post = font.get("post")
                if post is not None and float(post.formatType) != 3.0:
                    findings.append({"file": relative, "kind": "glyph-names"})
                font.close()
            except Exception:
                findings.append({"file": relative, "kind": "font-unreadable"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _ABSOLUTE_PATH.search(text):
            findings.append({"file": relative, "kind": "absolute-path"})
        if _TIMESTAMP.search(text):
            findings.append({"file": relative, "kind": "timestamp"})
        lowered = text.casefold()
        if any(
            re.search(
                rf"(?<![\w]){re.escape(word.casefold())}(?![\w])",
                lowered,
            )
            for word in forbidden
        ):
            findings.append({"file": relative, "kind": "mapping-hint"})
    return {
        "schema": PUBLIC_SCAN_SCHEMA,
        "status": "pass" if not findings else "fail",
        "files": len(files),
        "findingCount": len(findings),
        "findings": findings,
    }


def emit_canonical_artifacts(
    root: Path,
    *,
    mappings: Mapping[str, Mapping[str, str]],
    audit_font: Path,
    web_font: Path,
    public_fonts: Mapping[str, Path] | None = None,
    private_files: Mapping[str, Path] | None = None,
    css: Path,
    ruleset: Path,
    bundle_id: str,
    mapping_contract: Mapping[str, object],
    source_date_epoch: int,
    scan_public: bool,
) -> dict[str, object]:
    """Emit a canonical bundle with explicit public/private/verification tiers."""

    public = root / "public"
    private = root / "private"
    verification = root / "verification"
    for directory in (public, private, verification):
        directory.mkdir(parents=True, exist_ok=True)

    public_mapping = {
        "_meta": {
            "schema": PUBLIC_MAPPING_SCHEMA,
            "profile": "document-bound",
            "privacy": "public",
            "bundleId": bundle_id,
            "scopes": len(mappings),
        },
        "scopes": [
            {
                "scopeDigest": hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16],
                "pairs": len(mapping),
                "mappingDigest": hashlib.sha256(
                    json.dumps(
                        mapping,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest(),
            }
            for scope, mapping in sorted(mappings.items())
        ],
    }
    public_mapping_path = _write_json(public / "mapping.json", public_mapping)
    private_encoder_path = _write_json(
        private / "mapping.json",
        {
            "_meta": {
                "schema": PRIVATE_ENCODER_SCHEMA,
                "profile": "document-bound",
                "privacy": "private",
                "bundleId": bundle_id,
                "scopes": len(mappings),
            },
            "scopes": {
                scope: {source: mapping[source] for source in sorted(mapping)}
                for scope, mapping in sorted(mappings.items())
            },
        },
    )
    private_mapping_path = _write_json(
        private / "mapping.audit.json",
        {
            "schema": PRIVATE_MAPPING_SCHEMA,
            "privacy": "private",
            "bundleId": bundle_id,
            "mappingContract": dict(mapping_contract),
            "scopes": {
                scope: {
                    "mapping": {
                        source: mapping[source] for source in sorted(mapping)
                    },
                    "reverse": {
                        target: source
                        for target, source in sorted(
                            (target, source)
                            for source, target in mapping.items()
                        )
                    },
                }
                for scope, mapping in sorted(mappings.items())
            },
        },
    )
    private_csv = private / "mapping.audit.csv"
    with private_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["scope", "source", "target", "source_digest", "target_digest"]
        )
        for scope, mapping in sorted(mappings.items()):
            for source, target in sorted(mapping.items()):
                writer.writerow(
                    [
                        scope,
                        source,
                        target,
                        hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
                        hashlib.sha256(target.encode("utf-8")).hexdigest()[:16],
                    ]
                )

    audit_font_path = private / "font-audit.ttf"
    shutil.copyfile(audit_font, audit_font_path)
    web_font_path = _write_web_font(
        web_font,
        public / "font-web.woff2",
        epoch=source_date_epoch,
    )
    public_font_paths: list[Path] = []
    for name, public_source in sorted((public_fonts or {}).items()):
        destination = public / "fonts" / Path(name).name
        public_font_paths.append(
            _write_web_font(public_source, destination, epoch=source_date_epoch)
        )
    css_path = public / "shieldfont.css"
    shutil.copyfile(css, css_path)
    ruleset_path = private / "ruleset.json"
    shutil.copyfile(ruleset, ruleset_path)
    private_feature_paths: list[Path] = []
    for name, private_source in sorted((private_files or {}).items()):
        destination = private / "features" / Path(name).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_source, destination)
        private_feature_paths.append(destination)
    report_path = verification / "security-report.md"
    report_path.write_text(
        "# ShieldFont security report\n\n"
        "This bundle separates public delivery files from private audit material, "
        "uses opaque document identities, and raises the cost of casual scraping. "
        "It is not cryptography, confidentiality, authorization, or DRM.\n",
        encoding="utf-8",
    )

    scan = scan_public_artifacts(
        public,
        forbidden_words=(
            word
            for mapping in mappings.values()
            for pair in mapping.items()
            for word in pair
        ),
    )
    scan_path = _write_json(verification / "public-scan.json", scan)
    if scan_public and scan["status"] != "pass":
        raise ShieldFontError(
            "Canonical public artifact privacy scan failed",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="artifacts.privacy-scan",
            details={"findings": scan["findingCount"]},
        )

    records = [
        _record(
            public_mapping_path,
            root=root,
            schema=PUBLIC_MAPPING_SCHEMA,
            privacy="public",
        ),
        _record(
            web_font_path,
            root=root,
            schema="font/woff2.v1",
            privacy="public",
        ),
        _record(
            css_path,
            root=root,
            schema="text/css.v1",
            privacy="public",
        ),
        *[
            _record(
                path,
                root=root,
                schema="font/woff2.v1",
                privacy="public",
            )
            for path in public_font_paths
        ],
        _record(
            private_encoder_path,
            root=root,
            schema=PRIVATE_ENCODER_SCHEMA,
            privacy="private",
        ),
        _record(
            private_mapping_path,
            root=root,
            schema=PRIVATE_MAPPING_SCHEMA,
            privacy="private",
        ),
        _record(
            private_csv,
            root=root,
            schema=PRIVATE_MAPPING_SCHEMA,
            privacy="private",
        ),
        _record(
            audit_font_path,
            root=root,
            schema="font/ttf.v1",
            privacy="private",
        ),
        _record(
            ruleset_path,
            root=root,
            schema="shieldfont-ruleset/v1",
            privacy="private",
        ),
        *[
            _record(
                path,
                root=root,
                schema="shieldfont-layout-plan/v1",
                privacy="private",
            )
            for path in private_feature_paths
        ],
        _record(
            report_path,
            root=root,
            schema="shieldfont.security-report.v1",
            privacy="verification",
        ),
        _record(
            scan_path,
            root=root,
            schema=PUBLIC_SCAN_SCHEMA,
            privacy="verification",
        ),
    ]
    manifest: dict[str, Any] = {
        "schema": BUILD_MANIFEST_SCHEMA,
        "version": 1,
        "profile": "document-bound",
        "privacy": "public",
        "bundleId": bundle_id,
        "cacheIdentity": bundle_id,
        "mappingContract": dict(mapping_contract),
        "deterministic": True,
        "sourceDateEpoch": source_date_epoch,
        "artifacts": records,
    }
    _write_json(root / "build-manifest.json", manifest)
    return manifest
