"""Offline visible-text extraction and deterministic token frequencies."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError

_TOKEN_RE = re.compile(
    r"[^\W\d_]+(?:['’\-][^\W\d_]+)*",
    flags=re.UNICODE,
)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_CODE_RE = re.compile(r"```.*?```|`[^`]*`", flags=re.DOTALL)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def extract_visible_text(text: str, *, suffix: str = ".txt") -> str:
    """Extract visible content from plain text, HTML, or Markdown."""

    normalized = unicodedata.normalize("NFC", text)
    lowered_suffix = suffix.lower()
    if lowered_suffix in {".html", ".htm"} or "<html" in normalized.lower():
        parser = _VisibleTextParser()
        parser.feed(normalized)
        parser.close()
        return " ".join(parser.parts)
    if lowered_suffix in {".md", ".markdown"}:
        without_code = _MARKDOWN_CODE_RE.sub(" ", normalized)
        return html.unescape(_MARKDOWN_LINK_RE.sub(r"\1", without_code))
    return normalized


def extract_text_files(paths: Iterable[Path]) -> tuple[str, ...]:
    """Read and extract visible text without logging source content."""

    outputs: list[str] = []
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ShieldFontError(
                "Unable to read text corpus",
                code=ErrorCode.LLM_VALIDATION,
                exit_code=ExitCode.LLM_VALIDATION_ERROR,
                stage="llm_dictionary.extract",
                details={"path": str(path), "reason": type(error).__name__},
            ) from error
        outputs.append(extract_visible_text(raw, suffix=path.suffix))
    return tuple(outputs)


def token_frequencies(
    texts: Iterable[str],
    *,
    min_length: int = 2,
    stopwords: Iterable[str] = (),
    protected_terms: Iterable[str] = (),
) -> tuple[tuple[str, int], ...]:
    """Return deterministic Unicode word frequencies."""

    excluded = {
        unicodedata.normalize("NFC", word).casefold() for word in stopwords
    }
    protected = {
        unicodedata.normalize("NFC", word).casefold() for word in protected_terms
    }
    counts: Counter[str] = Counter()
    for text in texts:
        for token in _TOKEN_RE.findall(unicodedata.normalize("NFC", text)):
            if len(token) < min_length:
                continue
            folded = token.casefold()
            if folded in excluded or folded in protected:
                continue
            counts[folded] += 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def corpus_hash(texts: Iterable[str]) -> str:
    """Hash normalized corpus content without retaining its plaintext."""

    payload = "\n".join(
        unicodedata.normalize("NFC", text) for text in texts
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
