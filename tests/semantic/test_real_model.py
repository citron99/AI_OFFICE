"""Opt-in local model contract checks. Run with Docker --network none."""

import math
import os
from pathlib import Path

import pytest

from app.knowledge.local_embeddings import LocalSentenceTransformer


@pytest.fixture(scope="module")
def model() -> LocalSentenceTransformer:
    value = os.environ.get("TEST_SEMANTIC_MODEL_PATH")
    if not value:
        pytest.skip("TEST_SEMANTIC_MODEL_PATH is required; tests never download a model")
    return LocalSentenceTransformer(Path(value), 384)


def test_real_model_normalizes_and_is_repeatable(model: LocalSentenceTransformer) -> None:
    text = "Сотрудник обязан хранить коммерческую тайну."
    first = model.embed(text)
    assert len(first) == 384
    assert sum(v * v for v in first) == pytest.approx(1.0)
    assert all(math.isfinite(v) for v in first)
    assert model.embed(text) == pytest.approx(first, abs=1e-6)


def test_real_model_rejects_truncation(model: LocalSentenceTransformer) -> None:
    with pytest.raises(ValueError, match="token limit"):
        model.embed("обязательства " * 2000)


def test_real_model_splits_long_text_losslessly(model: LocalSentenceTransformer) -> None:
    text = "Стороны обязаны согласовать условия оплаты и срок исполнения. " * 30
    parts = model.split_text(text, max_parts=64)
    assert len(parts) > 1
    assert "".join(parts) == text
    for part in parts:
        assert len(model.embed(part)) == 384
