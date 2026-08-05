"""Candidate-only LLM dictionary orchestration and safe artifact export."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import (
    CandidateRequest,
    CandidateSuggestion,
    Provenance,
    ReviewStatus,
)
from shieldfont.domain.llm_dictionary.providers import (
    DictionaryCandidateProvider,
    OfflineCandidateProvider,
    parse_provider_response,
)
from shieldfont.domain.llm_dictionary.validation import (
    apply_review,
    pair_involution,
    require_approved,
    validate_candidates,
)
from shieldfont.infrastructure.llm_dictionary.extract import (
    corpus_hash,
    extract_text_files,
    token_frequencies,
)
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.llm_dictionary.application")
_PROMPT_TEMPLATE_VERSION = "shieldfont-llm-dictionary-candidate-v1"


@dataclass(frozen=True, slots=True)
class LlmDictionaryResult:
    """Generated candidate artifacts and their in-memory records."""

    candidates: tuple[CandidateSuggestion, ...]
    provenance: Provenance
    artifacts: dict[str, Path]


def _hash_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    return f"sha256:{hashlib.sha256(endpoint.encode('utf-8')).hexdigest()}"


def generate_candidate_dictionary(
    inputs: tuple[Path, ...],
    *,
    output_dir: Path,
    scope: str = "default",
    provider: DictionaryCandidateProvider | None = None,
    min_length: int = 2,
    stopwords: tuple[str, ...] = (),
    protected_terms: tuple[str, ...] = (),
    mapping_mode: str = "involution",
) -> LlmDictionaryResult:
    """Extract text and write candidates without ever approving them."""

    resolved_provider = provider or OfflineCandidateProvider()
    texts = extract_text_files(inputs)
    source_hash = corpus_hash(texts)
    frequencies = token_frequencies(
        texts,
        min_length=min_length,
        stopwords=stopwords,
        protected_terms=protected_terms,
    )
    log_event(
        LOGGER,
        logging.DEBUG,
        "Prepared LLM dictionary corpus",
        code="SF-LLM-CORPUS",
        stage="llm_dictionary.extract",
        details={
            "scope": scope,
            "files": len(inputs),
            "segments": len(frequencies),
            "sourceHash": source_hash,
        },
    )

    records: list[CandidateSuggestion] = []
    warnings: list[str] = []
    for source, frequency in frequencies:
        request = CandidateRequest(
            source=source,
            frequency=frequency,
            scope=scope,
            source_hash=source_hash,
        )
        payload = resolved_provider.generate(request)
        response = parse_provider_response(payload, expected_source=source)
        if not response.candidates:
            records.append(
                CandidateSuggestion(
                    source=source,
                    target="",
                    frequency=frequency,
                    status=ReviewStatus.REJECTED,
                    validation_errors=("no-provider-candidate",),
                )
            )
            warnings.append(f"no candidates returned for frequency token {source!r}")
            continue
        records.extend(
            CandidateSuggestion(
                source=source,
                target=candidate.target,
                pos=candidate.pos,
                morphology=candidate.morphology,
                rationale=candidate.rationale,
                confidence=candidate.confidence,
                frequency=frequency,
            )
            for candidate in response.candidates
        )

    validated = validate_candidates(records)
    if mapping_mode == "involution":
        paired = pair_involution(validated)
        validated = tuple(
            sorted(
                (
                    item
                    for item in validated
                    if item.status is ReviewStatus.REJECTED
                ),
                key=lambda item: (item.source, item.target),
            )
        ) + paired
    provenance = Provenance(
        provider=getattr(resolved_provider, "provider_name", "custom"),
        model=getattr(resolved_provider, "model", None),
        endpoint_hash=_hash_endpoint(getattr(resolved_provider, "endpoint", None)),
        prompt_hash=f"sha256:{hashlib.sha256(_PROMPT_TEMPLATE_VERSION.encode()).hexdigest()}",
        parameters={
            "scope": scope,
            "minLength": min_length,
            "mappingMode": mapping_mode,
        },
        timestamp=datetime.now(UTC).isoformat(),
        source_hash=source_hash,
        segments_count=len(frequencies),
        warnings=tuple(warnings),
    )
    artifacts = write_candidate_artifacts(
        validated,
        provenance,
        output_dir=output_dir,
        scope=scope,
    )
    log_event(
        LOGGER,
        logging.INFO,
        "LLM dictionary candidates written",
        code="SF-LLM-CANDIDATES-WRITTEN",
        stage="llm_dictionary.emit",
        details={
            "scope": scope,
            "candidates": len(validated),
            "rejected": sum(
                item.status is ReviewStatus.REJECTED for item in validated
            ),
        },
    )
    return LlmDictionaryResult(
        candidates=validated,
        provenance=provenance,
        artifacts=artifacts,
    )


def write_candidate_artifacts(
    candidates: tuple[CandidateSuggestion, ...],
    provenance: Provenance,
    *,
    output_dir: Path,
    scope: str,
) -> dict[str, Path]:
    """Write candidate CSV/review HTML/provenance without approved output."""

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / f"{scope}.candidates.csv"
    review_path = output_dir / f"{scope}.review.html"
    provenance_path = output_dir / f"{scope}.provenance.json"
    _write_candidate_csv(candidates, candidate_path)
    rows = "\n".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(value)}</td>"
            for value in (
                item.source,
                item.target,
                str(item.frequency),
                item.status.value,
                f"{item.confidence:.3f}",
                "; ".join(item.validation_errors),
            )
        )
        + "</tr>"
        for item in candidates
    )
    review_path.write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>ShieldFont review</title>"
        "<table><thead><tr><th>source</th><th>target</th><th>frequency</th>"
        "<th>status</th><th>confidence</th><th>validation</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>\n",
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps(provenance.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {
        "candidates": candidate_path,
        "review": review_path,
        "provenance": provenance_path,
    }


def load_candidate_csv(path: Path) -> tuple[CandidateSuggestion, ...]:
    """Read a generated candidate CSV for explicit review."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ShieldFontError(
            "Unable to read candidate CSV",
            code=ErrorCode.LLM_VALIDATION,
            exit_code=ExitCode.LLM_VALIDATION_ERROR,
            stage="llm_dictionary.review",
            details={"path": str(path), "reason": type(error).__name__},
        ) from error
    candidates: list[CandidateSuggestion] = []
    for row in rows:
        try:
            status = ReviewStatus(row.get("status", ReviewStatus.CANDIDATE))
            confidence = float(row.get("confidence", "0") or 0)
            frequency = int(row.get("frequency", "0") or 0)
        except ValueError as error:
            raise ShieldFontError(
                "Candidate CSV contains invalid review metadata",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.review",
                details={"path": str(path)},
            ) from error
        candidates.append(
            CandidateSuggestion(
                source=row.get("source", ""),
                target=row.get("target", ""),
                pos=row.get("pos", ""),
                morphology=row.get("morphology", ""),
                rationale=row.get("rationale", ""),
                confidence=confidence,
                frequency=frequency,
                status=status,
                validation_errors=tuple(
                    value
                    for value in (row.get("validation_errors", "") or "").split(";")
                    if value
                ),
            )
        )
    return tuple(candidates)


def review_and_export(
    candidates_path: Path,
    decisions: dict[tuple[str, str], ReviewStatus],
    *,
    reviewed_path: Path,
    approved_path: Path,
    mapping_mode: str = "involution",
) -> tuple[Path, Path]:
    """Apply explicit decisions and export approved mappings only."""

    candidates = load_candidate_csv(candidates_path)
    reviewed = apply_review(candidates, decisions)
    _write_candidate_csv(reviewed, reviewed_path)
    approved = require_approved(reviewed)
    if mapping_mode == "involution":
        approved_pairs = {(item.source, item.target) for item in approved}
        missing_reverse = sorted(
            (item.source, item.target)
            for item in approved
            if (item.target, item.source) not in approved_pairs
        )
        if missing_reverse:
            raise ShieldFontError(
                "Involution approvals must include reverse pairs",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.export",
                details={"missingReverse": missing_reverse},
            )
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    with approved_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["source", "target"])
        writer.writerows((item.source, item.target) for item in approved)
    return reviewed_path, approved_path


def _write_candidate_csv(
    candidates: tuple[CandidateSuggestion, ...],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "source",
                "target",
                "frequency",
                "status",
                "confidence",
                "pos",
                "morphology",
                "rationale",
                "validation_errors",
            ]
        )
        writer.writerows(
            (
                item.source,
                item.target,
                item.frequency,
                item.status.value,
                f"{item.confidence:.6f}",
                item.pos,
                item.morphology,
                item.rationale,
                ";".join(item.validation_errors),
            )
            for item in candidates
        )
