"""S3/MinIO storage backend (TZ 9.5: object storage, encrypted at rest).

Keys are namespaced by company so bucket policies can enforce the company
boundary server-side. All calls are synchronous boto3; FileService wraps
them in ``asyncio.to_thread`` exactly like the local backend.
"""

from typing import Any

from app.storage.keys import validate_object_key


class S3Storage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        prefix: str = "artifacts",
    ) -> None:
        import boto3  # imported lazily: optional dependency

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{validate_object_key(key)}"

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=self._key(key))
        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except self._client.exceptions.ClientError:
            return False
