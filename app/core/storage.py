from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings


class Storage:
    async def save(self, key: str, data: bytes, content_type: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def read(self, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def local_path(self, key: str) -> Path | None:
        return None

    def presigned_url(self, key: str, expires_seconds: int = 300) -> str | None:
        return None


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await run_in_threadpool(path.write_bytes, data)

    async def read(self, key: str) -> bytes:
        return await run_in_threadpool(self._path(key).read_bytes)

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.exists() else None


class S3Storage(Storage):
    def __init__(self, bucket: str, region: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        await run_in_threadpool(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def read(self, key: str) -> bytes:
        obj = await run_in_threadpool(self.client.get_object, Bucket=self.bucket, Key=key)
        return await run_in_threadpool(obj["Body"].read)

    def presigned_url(self, key: str, expires_seconds: int = 300) -> str | None:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds
        )


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage(s.s3_bucket, s.aws_region) if s.storage_backend == "s3" else LocalStorage(s.local_storage_dir)
    return _storage
