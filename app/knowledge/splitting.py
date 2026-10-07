"""Lossless, bounded subdivision; never decode tokens back into altered source text."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from app.core.exceptions import FileValidationError
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.parser import MAX_CHUNKS, TextBlock


@runtime_checkable
class TokenBoundedProvider(Protocol):
    def split_text(self, text: str, *, max_parts: int) -> list[str]: ...


def split_to_fit(text: str, fits: Callable[[str], bool], *, max_parts: int) -> list[str]:
    if max_parts < 1:
        raise FileValidationError("Embedding text exceeds part limit")
    pending = [text]
    parts: list[str] = []
    while pending:
        fragment = pending.pop()
        if fits(fragment):
            parts.append(fragment)
            continue
        if len(fragment) < 2:
            raise FileValidationError("A character exceeds the embedding token budget")
        # Prefer a whitespace boundary near the middle. Each child is re-tokenized:
        # token counts are not assumed monotonic with substring length.
        middle = len(fragment) // 2
        boundaries = [
            i + 1
            for i, char in enumerate(fragment)
            if char.isspace() and len(fragment) // 4 < i + 1 < 3 * len(fragment) // 4
        ]
        cut = min(boundaries, key=lambda value: abs(value - middle)) if boundaries else middle
        if len(parts) + len(pending) + 2 > max_parts:
            raise FileValidationError("Embedding text exceeds part limit")
        pending.extend([fragment[cut:], fragment[:cut]])
    return parts


def split_for_provider(text: str, provider: EmbeddingProvider, *, max_parts: int) -> list[str]:
    if max_parts < 1:
        raise FileValidationError("Embedding text exceeds part limit")
    if isinstance(provider, TokenBoundedProvider):
        parts = provider.split_text(text, max_parts=max_parts)
        if not parts or len(parts) > max_parts or any(not p for p in parts):
            raise FileValidationError("Invalid embedding text partition")
        if "".join(parts) != text:
            raise FileValidationError("Embedding text partition changed source text")
        return parts
    return [text]


def split_chunks(chunks: list[TextBlock], provider: EmbeddingProvider) -> list[TextBlock]:
    result: list[TextBlock] = []
    for chunk in chunks:
        parts = split_for_provider(chunk.text, provider, max_parts=MAX_CHUNKS - len(result))
        result.extend(
            TextBlock(
                part,
                chunk.locator if len(parts) == 1 else f"{chunk.locator}; token part {index}",
                chunk.page,
                chunk.article,
            )
            for index, part in enumerate(parts, 1)
        )
    return result
