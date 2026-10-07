"""Storage backend factory (settings-driven)."""

from app.config import Settings
from app.storage import LocalDirectoryStorage, ObjectStorage, S3Storage


def create_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "s3":
        if not (settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key):
            raise RuntimeError(
                "storage_backend=s3 requires S3_ENDPOINT_URL, S3_ACCESS_KEY and S3_SECRET_KEY"
            )
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        )
    return LocalDirectoryStorage(settings.upload_dir)
