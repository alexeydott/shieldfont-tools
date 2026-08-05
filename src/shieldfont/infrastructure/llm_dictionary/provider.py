"""Offline provider adapters for structured candidate fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import CandidateRequest


class JsonFileCandidateProvider:
    """Read schema-shaped responses from a local JSON fixture.

    The file is intentionally an explicit adapter rather than an implicit
    network fallback, so offline runs remain deterministic and auditable.
    """

    provider_name: str = "json-file"
    model: str | None = None
    endpoint: str | None = None

    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ShieldFontError(
                "Provider response fixture must be a JSON object",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.provider_fixture",
                details={"path": str(path)},
            )
        self._responses: dict[str, Any] = payload

    def generate(self, request: CandidateRequest) -> dict[str, object]:
        response = self._responses.get(request.source)
        if response is None:
            return {"source": request.source, "candidates": []}
        if not isinstance(response, dict):
            return {"source": request.source, "candidates": response}
        return response
