"""Object storage abstraction (TZ 9.5: encrypted-at-rest object storage).

Two backends behind one contract: a local directory (pilot default) and an
S3/MinIO bucket. The artifact row keeps its opaque ``storage_key`` either
way; nothing else in the codebase knows where bytes physically live.
"""

from typing import Protocol

from app.storage.local import LocalDirectoryStorage
from app.storage.s3 import S3Storage

__all__ = ["LocalDirectoryStorage", "ObjectStorage", "S3Storage"]


class ObjectStorage(Protocol):
    """Byte-store contract for original artifacts (ART-004)."""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
