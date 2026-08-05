"""Provider interfaces and strict structured-response parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, Protocol, cast

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import CandidateRequest


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    """Validated candidate payload returned by a provider."""

    target: str
    pos: str = ""
    morphology: str = ""
    rationale: str = ""
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Validated response matching the published JSON Schema."""

    source: str
    candidates: tuple[ProviderCandidate, ...]


class DictionaryCandidateProvider(Protocol):
    """Optional provider port; implementations must not mutate approved data."""

    provider_name: str
    model: str | None
    endpoint: str | None

    def generate(self, request: CandidateRequest) -> Mapping[str, object]:
        """Return one schema-shaped candidate response."""


class OfflineCandidateProvider:
    """No-network provider used by default for safe offline workflows."""

    provider_name = "offline"
    model = None
    endpoint = None

    def generate(self, request: CandidateRequest) -> Mapping[str, object]:
        return {"source": request.source, "candidates": []}


_ALLOWED_RESPONSE_KEYS = {"source", "candidates"}
_ALLOWED_CANDIDATE_KEYS = {
    "target",
    "pos",
    "morphology",
    "rationale",
    "confidence",
}


def parse_provider_response(
    payload: Mapping[str, object],
    *,
    expected_source: str,
) -> ProviderResponse:
    """Validate a provider response without trusting model confidence."""

    if set(payload.keys()) != _ALLOWED_RESPONSE_KEYS:
        _raise_invalid("Provider response has unexpected or missing fields")
    source = payload.get("source")
    candidates = payload.get("candidates")
    if source != expected_source or not isinstance(source, str):
        _raise_invalid("Provider response source does not match the request")
    if not isinstance(candidates, list):
        _raise_invalid("Provider response candidates must be an array")

    parsed: list[ProviderCandidate] = []
    for raw_candidate in cast(list[object], candidates):
        if not isinstance(raw_candidate, Mapping):
            _raise_invalid("Provider candidate must be an object")
        candidate = cast(Mapping[str, object], raw_candidate)
        if not set(candidate.keys()).issubset(_ALLOWED_CANDIDATE_KEYS):
            _raise_invalid("Provider candidate has unexpected fields")
        target = candidate.get("target")
        if not isinstance(target, str) or not target:
            _raise_invalid("Provider candidate target must be a non-empty string")
        confidence = candidate.get("confidence", 0.0)
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            _raise_invalid("Provider candidate confidence must be between 0 and 1")
        text_fields: dict[str, str] = {}
        for field_name in ("pos", "morphology", "rationale"):
            value = candidate.get(field_name, "")
            if not isinstance(value, str):
                _raise_invalid(f"Provider candidate {field_name} must be a string")
            text_fields[field_name] = value
        parsed.append(
            ProviderCandidate(
                target=target,
                confidence=float(confidence),
                **text_fields,
            )
        )
    return ProviderResponse(source=source, candidates=tuple(parsed))


def _raise_invalid(message: str) -> NoReturn:
    raise ShieldFontError(
        message,
        code=ErrorCode.LLM_VALIDATION,
        exit_code=ExitCode.LLM_VALIDATION_ERROR,
        stage="llm_dictionary.provider_response",
    )
