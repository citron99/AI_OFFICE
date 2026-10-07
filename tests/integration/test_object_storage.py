"""Object storage backends: local contract + opt-in MinIO integration (TZ 9.5).

Set TEST_S3_URL (e.g. http://127.0.0.1:9000) with TEST_S3_ACCESS_KEY /
TEST_S3_SECRET_KEY / TEST_S3_BUCKET to run the MinIO scenarios.
"""

import os
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import Headers, UploadFile

from app.config import Settings
from app.db.session import create_session_factory
from app.services.files import FileService
from app.storage import LocalDirectoryStorage, S3Storage
from app.storage.factory import create_storage


def test_local_backend_roundtrip(tmp_path) -> None:
    storage = LocalDirectoryStorage(tmp_path)
    storage.put("0" * 32, b"artifact bytes")
    assert storage.exists("0" * 32)
    assert storage.get("0" * 32) == b"artifact bytes"
    storage.delete("0" * 32)
    assert not storage.exists("0" * 32)


def test_invalid_keys_are_rejected(tmp_path) -> None:
    storage = LocalDirectoryStorage(tmp_path)
    with pytest.raises(ValueError, match="storage key"):
        storage.put("../escape", b"x")
    with pytest.raises(ValueError, match="storage key"):
        S3Storage(
            endpoint_url="http://localhost:9000",
            bucket="b",
            access_key="k",
            secret_key="s",
        ).get("not-a-key")


def test_s3_accepts_the_same_company_namespaced_key_as_local() -> None:
    storage = S3Storage(
        endpoint_url="http://localhost:9000",
        bucket="b",
        access_key="k",
        secret_key="s",
    )
    assert storage._key(f"comp_one/{'a' * 32}") == f"artifacts/comp_one/{'a' * 32}"  # noqa: SLF001


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects


def upload(name: str = "report.txt") -> UploadFile:
    return UploadFile(
        BytesIO(b"compensated artifact"),
        filename=name,
        headers=Headers({"content-type": "text/plain"}),
    )


async def test_upload_removes_object_when_database_commit_fails(
    engine,
    tmp_path,
    monkeypatch,
) -> None:
    storage = MemoryStorage()
    async with create_session_factory(engine)() as session:
        monkeypatch.setattr(
            session,
            "commit",
            AsyncMock(side_effect=RuntimeError("commit failed")),
        )
        service = FileService(
            session,
            Settings(app_env="test", upload_dir=tmp_path),
            storage,
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            await service.upload(upload(), owner_id="owner", company_id="comp_one")
    assert storage.objects == {}


async def test_delete_restores_object_when_database_commit_fails(
    engine,
    tmp_path,
    monkeypatch,
) -> None:
    storage = MemoryStorage()
    async with create_session_factory(engine)() as session:
        service = FileService(
            session,
            Settings(app_env="test", upload_dir=tmp_path),
            storage,
        )
        record = await service.upload(
            upload(),
            owner_id="owner",
            company_id="comp_one",
        )
        object_key = f"comp_one/{record.storage_key}"
        monkeypatch.setattr(
            session,
            "commit",
            AsyncMock(side_effect=RuntimeError("commit failed")),
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            await service.delete(
                record.id,
                owner_id="owner",
                company_id="comp_one",
            )
    assert storage.objects[object_key] == b"compensated artifact"


def test_factory_defaults_to_local(tmp_path) -> None:
    settings = Settings(app_env="test", upload_dir=tmp_path)
    assert isinstance(create_storage(settings), LocalDirectoryStorage)


def test_factory_requires_s3_configuration() -> None:
    with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
        create_storage(Settings(app_env="test", storage_backend="s3"))


@pytest.mark.skipif(
    not os.environ.get("TEST_S3_URL"), reason="TEST_S3_URL is required for MinIO tests"
)
async def test_s3_backend_roundtrip_against_minio() -> None:
    storage = S3Storage(
        endpoint_url=os.environ["TEST_S3_URL"],
        bucket=os.environ.get("TEST_S3_BUCKET", "ai-office-artifacts"),
        access_key=os.environ.get("TEST_S3_ACCESS_KEY", "aitest"),
        secret_key=os.environ.get("TEST_S3_SECRET_KEY", "aitest-secret"),
    )
    key = "a" * 32
    storage.put(key, b"artifact from the unified office")
    assert storage.exists(key)
    assert storage.get(key) == b"artifact from the unified office"
    storage.delete(key)
    assert not storage.exists(key)


@pytest.mark.skipif(
    not os.environ.get("TEST_S3_URL"), reason="TEST_S3_URL is required for MinIO tests"
)
async def test_file_service_uses_s3_backend(engine, tmp_path) -> None:
    """Upload→download→delete through the app with storage_backend=s3."""
    import httpx

    from app.db.session import create_session_factory
    from app.main import create_app

    settings = Settings(
        app_env="test",
        upload_dir=tmp_path / "uploads",
        storage_backend="s3",
        s3_endpoint_url=os.environ["TEST_S3_URL"],
        s3_access_key=os.environ.get("TEST_S3_ACCESS_KEY", "aitest"),
        s3_secret_key=os.environ.get("TEST_S3_SECRET_KEY", "aitest-secret"),
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                "/api/v1/files",
                files={"file": ("report.txt", b"S3 backend artifact", "text/plain")},
            )
            assert uploaded.status_code == 201, uploaded.text
            artifact_id = uploaded.json()["id"]
            downloaded = await client.get(f"/api/v1/files/{artifact_id}")
            assert downloaded.status_code == 200
            assert downloaded.content == b"S3 backend artifact"
            deleted = await client.delete(f"/api/v1/files/{artifact_id}")
            assert deleted.status_code == 200
            assert (await client.get(f"/api/v1/files/{artifact_id}")).status_code == 404
