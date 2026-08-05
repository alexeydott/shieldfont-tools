from __future__ import annotations

import json
from pathlib import Path

import pytest

from shieldfont.application.llm_dictionary import (
    generate_candidate_dictionary,
    review_and_export,
)
from shieldfont.domain.errors import ErrorCode, ShieldFontError
from shieldfont.domain.llm_dictionary.models import (
    CandidateRequest,
    CandidateSuggestion,
    ReviewStatus,
)
from shieldfont.domain.llm_dictionary.providers import parse_provider_response
from shieldfont.domain.llm_dictionary.validation import (
    apply_review,
    pair_involution,
    validate_candidate,
)
from shieldfont.infrastructure.llm_dictionary.extract import (
    extract_visible_text,
    token_frequencies,
)


class FixtureProvider:
    provider_name = "fixture"
    model = "fixture-v1"
    endpoint = "https://example.invalid/provider?key=secret"

    def generate(self, request: CandidateRequest) -> dict[str, object]:
        return {
            "source": request.source,
            "candidates": [
                {
                    "target": "target",
                    "pos": "noun",
                    "confidence": 0.9,
                }
            ],
        }


def test_visible_extraction_and_frequency_are_deterministic() -> None:
    assert extract_visible_text(
        "<p>Hello <b>world</b></p><script>secret</script>",
        suffix=".html",
    ) == "Hello  world"
    assert token_frequencies(["World world hello"], min_length=2) == (
        ("world", 2),
        ("hello", 1),
    )


def test_provider_response_is_strictly_schema_shaped() -> None:
    response = parse_provider_response(
        {"source": "word", "candidates": [{"target": "mot", "confidence": 0.5}]},
        expected_source="word",
    )
    assert response.candidates[0].target == "mot"

    with pytest.raises(ShieldFontError) as error:
        parse_provider_response(
            {"source": "word", "candidates": [], "secret": "leak"},
            expected_source="word",
        )
    assert error.value.code is ErrorCode.LLM_VALIDATION


def test_deterministic_validator_rejects_markup_identity_and_bad_script() -> None:
    candidate = validate_candidate(
        CandidateSuggestion("Word", "{{value}}"),
        source_script="latin",
        target_script="latin",
    )
    assert candidate.status is ReviewStatus.REJECTED
    assert {"protected-markup", "token-boundary"} <= set(
        candidate.validation_errors
    )


def test_pairing_and_review_keep_approval_explicit() -> None:
    candidates = [
        validate_candidate(CandidateSuggestion("one", "uno", confidence=0.8)),
        validate_candidate(CandidateSuggestion("two", "dos", confidence=0.7)),
    ]
    paired = pair_involution(candidates)
    assert {(item.source, item.target) for item in paired} == {
        ("one", "uno"),
        ("uno", "one"),
        ("two", "dos"),
        ("dos", "two"),
    }
    reviewed = apply_review(
        paired,
        {
            ("one", "uno"): ReviewStatus.APPROVED,
            ("uno", "one"): ReviewStatus.APPROVED,
        },
    )
    assert sum(item.status is ReviewStatus.APPROVED for item in reviewed) == 2


def test_generation_is_offline_by_default_and_never_writes_approved(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("word word other", encoding="utf-8")
    result = generate_candidate_dictionary(
        (corpus,),
        output_dir=tmp_path / "generated",
    )
    assert result.provenance.provider == "offline"
    assert result.artifacts["candidates"].exists()
    assert not (tmp_path / "generated/default.approved.csv").exists()


def test_review_exports_only_validated_approved_rows(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("word", encoding="utf-8")
    result = generate_candidate_dictionary(
        (corpus,),
        output_dir=tmp_path / "generated",
        provider=FixtureProvider(),
    )
    decisions = {
        ("word", "target"): ReviewStatus.APPROVED,
        ("target", "word"): ReviewStatus.APPROVED,
    }
    reviewed, approved = review_and_export(
        result.artifacts["candidates"],
        decisions,
        reviewed_path=tmp_path / "reviewed.csv",
        approved_path=tmp_path / "approved.csv",
    )
    assert reviewed.exists()
    assert approved.read_text(encoding="utf-8-sig").splitlines() == [
        "source,target",
        "target,word",
        "word,target",
    ]
    provenance = json.loads(
        result.artifacts["provenance"].read_text(encoding="utf-8")
    )
    assert "secret" not in json.dumps(provenance)
