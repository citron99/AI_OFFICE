"""Deterministic local baseline. NOT semantic embeddings or a production model."""

import hashlib
import math
import re
from typing import Protocol

DIMENSIONS = 128
MODEL_ID = "mock-token-hash-v1-128"
RETRIEVAL_VERSION = "mock-hash-lexical-v2"


def tokens(text: str) -> list[str]:
    """Same tokenization as v1 embeddings; deliberately no stemming or translation."""
    return re.findall(r"\w+", text.casefold())


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int
    semantic: bool

    def embed(self, text: str) -> list[float]: ...


class HashEmbeddingProvider:
    model_id = MODEL_ID
    dimensions = DIMENSIONS
    semantic = False

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        length = math.sqrt(sum(value * value for value in vector))
        return [value / length for value in vector] if length else vector


def validate_vector(
    vector: list[float], dimensions: int, *, allow_zero: bool = False
) -> list[float]:
    if len(vector) != dimensions or not all(math.isfinite(value) for value in vector):
        raise ValueError("Invalid embedding dimensions or non-finite values")
    length = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(length) or (not length and not allow_zero):
        raise ValueError("Invalid zero or overflowing embedding")
    return [value / length for value in vector] if length else vector
