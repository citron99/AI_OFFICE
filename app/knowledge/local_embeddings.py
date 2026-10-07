"""Opt-in local Sentence Transformers adapter. No automatic downloads."""

import hashlib
import importlib
import json
import threading
from pathlib import Path
from typing import Any

from app.config import Settings
from app.knowledge.embeddings import EmbeddingProvider, HashEmbeddingProvider, validate_vector
from app.knowledge.splitting import split_to_fit


class LocalSentenceTransformer:
    semantic = True

    def __init__(self, path: Path, dimensions: int) -> None:
        if not path.is_dir():
            raise ValueError("Embedding model must be an existing trusted local directory")
        # Bind model identity to files, not a mutable directory name or user label.
        digest = hashlib.sha256()
        files = sorted(p for p in path.rglob("*") if p.is_file())
        if not files:
            raise ValueError("Embedding model directory is empty")
        for file in files:
            if file.is_symlink():
                raise ValueError("Embedding model snapshot must not contain symlinks")
            digest.update(json.dumps(file.relative_to(path).as_posix()).encode())
            digest.update(file.stat().st_size.to_bytes(8, "big"))
            with file.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
        # New ingestion/query subdivision policy gets a separate immutable namespace.
        self.model_id = f"st-local-v2:{digest.hexdigest()}"
        self.dimensions = dimensions
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError(
                "Install optional requirements-semantic.txt to use local embeddings"
            ) from exc
        self.model: Any = module.SentenceTransformer(
            str(path.resolve()),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
        )
        if self.model.get_sentence_embedding_dimension() != dimensions:
            raise ValueError("Configured dimensions do not match the local model")
        if getattr(self.model, "default_prompt_name", None) is not None:
            raise ValueError("Prompt-specific models require a dedicated query/document adapter")
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._lock:
            # Do not silently accept model token truncation of a legal source.
            encoded = self.model.tokenizer(text, truncation=False, add_special_tokens=True)
            if len(encoded["input_ids"]) > self.model.max_seq_length:
                raise ValueError("Text exceeds embedding model token limit; use smaller chunks")
            vector = self.model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return validate_vector([float(value) for value in vector], self.dimensions)

    def split_text(self, text: str, *, max_parts: int) -> list[str]:
        with self._lock:

            def fits(fragment: str) -> bool:
                encoded = self.model.tokenizer(fragment, truncation=False, add_special_tokens=True)
                return bool(len(encoded["input_ids"]) <= self.model.max_seq_length)

            return split_to_fit(text, fits, max_parts=max_parts)


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "mock":
        return HashEmbeddingProvider()
    if settings.embedding_model_path is None:
        raise ValueError("EMBEDDING_MODEL_PATH is required for local semantic embeddings")
    return LocalSentenceTransformer(settings.embedding_model_path, settings.embedding_dimensions)
