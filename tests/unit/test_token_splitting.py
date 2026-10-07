import pytest

from app.core.exceptions import FileValidationError
from app.knowledge.embeddings import HashEmbeddingProvider
from app.knowledge.parser import TextBlock
from app.knowledge.splitting import split_chunks, split_for_provider, split_to_fit


@pytest.mark.parametrize("text", ["word " * 100, "безпробелов" * 30, "🙂\n\t世界 " * 30])
def test_partition_preserves_every_character(text: str) -> None:
    parts = split_to_fit(text, lambda value: len(value) <= 17, max_parts=100)
    assert "".join(parts) == text
    assert all(0 < len(part) <= 17 for part in parts)


def test_does_not_assume_monotonic_token_counts() -> None:
    parts = split_to_fit("abcdef", lambda value: len(value) in {1, 3}, max_parts=6)
    assert parts == ["abc", "def"]


def test_overflow_and_impossible_budget_fail_closed() -> None:
    with pytest.raises(FileValidationError, match="part limit"):
        split_to_fit("abcdef", lambda value: len(value) <= 1, max_parts=5)
    with pytest.raises(FileValidationError, match="character"):
        split_to_fit("a", lambda _: False, max_parts=5)


class SmallProvider(HashEmbeddingProvider):
    def split_text(self, text: str, *, max_parts: int) -> list[str]:
        return split_to_fit(text, lambda value: len(value) <= 3, max_parts=max_parts)


def test_metadata_and_baseline_remain_intact() -> None:
    original = TextBlock("abcdef", "page 2; part 1", 2, "Article 3")
    assert split_chunks([original], HashEmbeddingProvider()) == [original]
    chunks = split_chunks([original], SmallProvider())
    assert "".join(c.text for c in chunks) == original.text
    assert all(c.page == 2 and c.article == "Article 3" for c in chunks)
    assert chunks[1].locator == "page 2; part 1; token part 2"


def test_provider_cannot_silently_drop_text() -> None:
    class Bad(SmallProvider):
        def split_text(self, text: str, *, max_parts: int) -> list[str]:
            return [text[:1]]

    with pytest.raises(FileValidationError, match="changed source"):
        split_for_provider("abcdef", Bad(), max_parts=3)


def test_document_global_chunk_limit_applies_after_subdivision() -> None:
    chunks = [TextBlock("abcdef", "text")] * 1001
    with pytest.raises(FileValidationError, match="part limit"):
        split_chunks(chunks, SmallProvider())
