"""Provider-neutral models for candidate-only LLM dictionary generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ReviewStatus(StrEnum):
    """Review lifecycle states for generated dictionary suggestions."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs-review"


@dataclass(frozen=True, slots=True)
class CandidateRequest:
    """Privacy-minimal provider request for one source token."""

    source: str
    frequency: int
    scope: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class CandidateSuggestion:
    """One structured provider suggestion before human approval."""

    source: str
    target: str
    pos: str = ""
    morphology: str = ""
    rationale: str = ""
    confidence: float = 0.0
    status: ReviewStatus = ReviewStatus.CANDIDATE
    validation_errors: tuple[str, ...] = ()
    frequency: int = 0

    @property
    def is_valid(self) -> bool:
        return not self.validation_errors


@dataclass(frozen=True, slots=True)
class Provenance:
    """Secret-safe provenance attached to generated candidate artifacts."""

    provider: str
    model: str | None
    endpoint_hash: str | None
    prompt_hash: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    timestamp: str = ""
    source_hash: str = ""
    segments_count: int = 0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "endpointHash": self.endpoint_hash,
            "promptHash": self.prompt_hash,
            "parameters": dict(self.parameters),
            "timestamp": self.timestamp,
            "sourceHash": self.source_hash,
            "segmentsCount": self.segments_count,
            "warnings": list(self.warnings),
        }
