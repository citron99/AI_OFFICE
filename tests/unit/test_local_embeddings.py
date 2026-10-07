from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.knowledge.embeddings import validate_vector
from app.knowledge.local_embeddings import LocalSentenceTransformer


@pytest.mark.parametrize(
    "vector,dimension", [([1.0], 2), ([float("nan")], 1), ([float("inf")], 1), ([0.0], 1)]
)
def test_bad_embeddings_rejected(vector: list[float], dimension: int) -> None:
    with pytest.raises(ValueError):
        validate_vector(vector, dimension)


def test_normalizes_provider_vectors() -> None:
    assert validate_vector([3, 4], 2) == [0.6, 0.8]


def test_missing_model_does_not_import_or_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: str) -> None:
        raise AssertionError("must not try to load missing model")

    monkeypatch.setattr("app.knowledge.local_embeddings.importlib.import_module", forbidden)
    with pytest.raises(ValueError, match="existing trusted"):
        LocalSentenceTransformer(tmp_path / "missing", 2)


def test_local_only_constructor_and_dimension_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.json").write_text("{}")
    calls = []

    class Model:
        max_seq_length = 5

        def __init__(self, path: str, **kwargs: Any) -> None:
            calls.append(kwargs)

        def get_sentence_embedding_dimension(self) -> int:
            return 2

        def tokenizer(self, text: str, **kwargs: Any) -> dict[str, list[int]]:
            assert kwargs["truncation"] is False
            return {"input_ids": [1] * len(text.split())}

        def encode(self, text: str, **kwargs: Any) -> list[float]:
            assert kwargs["normalize_embeddings"]
            return [3, 4]

    monkeypatch.setattr(
        "app.knowledge.local_embeddings.importlib.import_module",
        lambda _: SimpleNamespace(SentenceTransformer=Model),
    )
    provider = LocalSentenceTransformer(tmp_path, 2)
    assert calls[0] == {"device": "cpu", "local_files_only": True, "trust_remote_code": False}
    assert provider.embed("test") == [0.6, 0.8]
    assert provider.model_id.startswith("st-local-v2:")
    assert LocalSentenceTransformer(tmp_path, 2).model_id == provider.model_id
    with pytest.raises(ValueError, match="token limit"):
        provider.embed("one two three four five six")
    original = "one two three four five six seven eight nine"
    parts = provider.split_text(original, max_parts=20)
    assert "".join(parts) == original
    assert len(parts) > 1
    for part in parts:
        provider.embed(part)
    with pytest.raises(ValueError, match="dimensions"):
        LocalSentenceTransformer(tmp_path, 3)
    (tmp_path / "config.json").write_text('{"changed":true}')
    assert LocalSentenceTransformer(tmp_path, 2).model_id != provider.model_id
