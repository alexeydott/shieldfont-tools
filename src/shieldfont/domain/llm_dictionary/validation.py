"""Deterministic validation and pairing for LLM dictionary candidates."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import (
    CandidateSuggestion,
    ReviewStatus,
)

_WORD_RE = re.compile(r"^[^\W\d_]+(?:['’\-][^\W\d_]+)*$", re.UNICODE)
_PROTECTED_RE = re.compile(r"(<[^>]+>|{{.*?}}|{%.*?%}|&[A-Za-z][^;]*;)")


def detect_script(value: str) -> str:
    """Return a conservative script label using Unicode character names."""

    scripts: set[str] = set()
    for character in value:
        name = unicodedata.name(character, "")
        for marker, script in (
            ("LATIN", "latin"),
            ("CYRILLIC", "cyrillic"),
            ("GREEK", "greek"),
            ("ARABIC", "arabic"),
            ("HEBREW", "hebrew"),
            ("DEVANAGARI", "devanagari"),
        ):
            if marker in name:
                scripts.add(script)
                break
    if len(scripts) == 1:
        return next(iter(scripts))
    return "mixed" if scripts else "common"


def validate_candidate(
    candidate: CandidateSuggestion,
    *,
    source_script: str | None = None,
    target_script: str | None = None,
    deny: Iterable[str] = (),
    glyph_exists: Callable[[int], bool] | None = None,
) -> CandidateSuggestion:
    """Apply deterministic safety checks and return a classified candidate."""

    reasons: list[str] = []
    source = unicodedata.normalize("NFC", candidate.source).strip()
    target = unicodedata.normalize("NFC", candidate.target).strip()
    if not source or not target:
        reasons.append("empty-source-or-target")
    if source == target:
        reasons.append("identity-mapping")
    if any(unicodedata.category(char).startswith("C") for char in source + target):
        reasons.append("control-character")
    if _PROTECTED_RE.search(source) or _PROTECTED_RE.search(target):
        reasons.append("protected-markup")
    if not _WORD_RE.fullmatch(source) or not _WORD_RE.fullmatch(target):
        reasons.append("token-boundary")
    if source_script and detect_script(source) != source_script:
        reasons.append("source-script")
    if target_script and detect_script(target) != target_script:
        reasons.append("target-script")
    if target in set(deny) or source in set(deny):
        reasons.append("deny-listed")
    if candidate.confidence < 0 or candidate.confidence > 1:
        reasons.append("confidence-range")
    if source.isupper() != target.isupper() and source.islower() != target.islower():
        reasons.append("case-incompatible")
    if glyph_exists is not None:
        missing = [
            f"U+{ord(character):04X}"
            for character in source + target
            if not glyph_exists(ord(character))
        ]
        if missing:
            reasons.append("missing-glyph:" + ",".join(sorted(set(missing))))
    status = ReviewStatus.REJECTED if reasons else ReviewStatus.CANDIDATE
    return replace(
        candidate,
        source=source,
        target=target,
        status=status,
        validation_errors=tuple(sorted(set(reasons))),
    )


def validate_candidates(
    candidates: Iterable[CandidateSuggestion],
    *,
    source_script: str | None = None,
    target_script: str | None = None,
    deny: Iterable[str] = (),
    glyph_exists: Callable[[int], bool] | None = None,
) -> tuple[CandidateSuggestion, ...]:
    """Validate and deterministically sort provider candidates."""

    validated = tuple(
        validate_candidate(
            candidate,
            source_script=source_script,
            target_script=target_script,
            deny=deny,
            glyph_exists=glyph_exists,
        )
        for candidate in candidates
    )
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.source,
                item.status.value,
                -item.confidence,
                item.target,
            ),
        )
    )


def pair_involution(
    candidates: Iterable[CandidateSuggestion],
) -> tuple[CandidateSuggestion, ...]:
    """Select an injective maximum matching and materialize reverse pairs."""

    valid = [
        candidate
        for candidate in candidates
        if candidate.status is ReviewStatus.CANDIDATE and candidate.is_valid
    ]
    adjacency: dict[str, list[CandidateSuggestion]] = {}
    for candidate in sorted(
        valid,
        key=lambda item: (-item.confidence, item.source, item.target),
    ):
        adjacency.setdefault(candidate.source, []).append(candidate)
    matched_target: dict[str, str] = {}
    selected: dict[tuple[str, str], CandidateSuggestion] = {}

    def visit(source: str, seen: set[str]) -> bool:
        for candidate in adjacency.get(source, ()):
            if candidate.target in seen:
                continue
            seen.add(candidate.target)
            previous = matched_target.get(candidate.target)
            if previous is None or visit(previous, seen):
                matched_target[candidate.target] = source
                selected[(source, candidate.target)] = candidate
                return True
        return False

    for source in sorted(adjacency):
        visit(source, set())

    result: dict[tuple[str, str], CandidateSuggestion] = dict(selected)
    for (source, target), candidate in sorted(selected.items()):
        result.setdefault(
            (target, source),
            replace(candidate, source=target, target=source),
        )
    return tuple(
        sorted(result.values(), key=lambda item: (item.source, item.target))
    )


def apply_review(
    candidates: Iterable[CandidateSuggestion],
    decisions: Mapping[tuple[str, str], ReviewStatus],
) -> tuple[CandidateSuggestion, ...]:
    """Apply explicit review decisions, refusing approval of invalid rows."""

    reviewed: list[CandidateSuggestion] = []
    for candidate in candidates:
        decision = decisions.get(
            (candidate.source, candidate.target),
            candidate.status,
        )
        if decision is ReviewStatus.APPROVED and not candidate.is_valid:
            raise ShieldFontError(
                "Invalid candidate cannot be approved",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.review",
                details={
                    "source": candidate.source,
                    "target": candidate.target,
                    "reasons": list(candidate.validation_errors),
                },
            )
        reviewed.append(replace(candidate, status=decision))
    return tuple(reviewed)


def require_approved(
    candidates: Iterable[CandidateSuggestion],
) -> tuple[CandidateSuggestion, ...]:
    """Return only validated approvals, failing closed on invalid approvals."""

    approved = tuple(
        candidate
        for candidate in candidates
        if candidate.status is ReviewStatus.APPROVED
    )
    invalid = [candidate for candidate in approved if not candidate.is_valid]
    if invalid:
        raise ShieldFontError(
            "Approved output contains invalid candidates",
            code=ErrorCode.LLM_VALIDATION,
            exit_code=ExitCode.LLM_VALIDATION_ERROR,
            stage="llm_dictionary.export",
            details={"count": len(invalid)},
        )
    return tuple(sorted(approved, key=lambda item: (item.source, item.target)))
