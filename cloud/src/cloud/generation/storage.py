"""结果与输入文件存储。

生产用 Cloudflare R2 的 S3 兼容接口:浏览器/桌面端拿预签名 URL 直传,服务端只读写对象,
不中转用户的上传流量。本地开发仍用磁盘实现,测试因此不依赖网络。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from cloud.generation.adapters import AdapterArtifact


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    size: int
    sha256: str


class ArtifactStorage(Protocol):
    """Cloud 只依赖这四件事:落盘/直传签名/读取签名/公开地址。"""

    direct_upload: bool

    def save(self, *, user_id: str, job_id: str, artifact: AdapterArtifact) -> StoredArtifact: ...

    def presign_put(self, *, storage_key: str, mime: str, expires_in: int = 900) -> str: ...

    def presign_get(self, *, storage_key: str, expires_in: int = 3600) -> str: ...

    def public_url(self, storage_key: str) -> str | None: ...


class LocalArtifactStorage:
    direct_upload = False

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, *, user_id: str, job_id: str, artifact: AdapterArtifact) -> StoredArtifact:
        digest = hashlib.sha256(artifact.data).hexdigest()
        relative = Path(user_id) / job_id / f"{digest[:16]}-{artifact.filename}"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(artifact.data)
        os.replace(temporary, target)
        return StoredArtifact(storage_key=str(relative), size=len(artifact.data), sha256=digest)

    def path(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("artifact path escapes storage root")
        return candidate

    def presign_put(self, *, storage_key: str, mime: str, expires_in: int = 900) -> str:
        raise NotImplementedError("local storage has no direct upload")

    def presign_get(self, *, storage_key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError("local storage has no presigned reads")

    def public_url(self, storage_key: str) -> str | None:
        return None


class R2ArtifactStorage:
    """Cloudflare R2。`public_base_url` 是绑定到桶的自定义域名。"""

    direct_upload = True

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
        client: object | None = None,
    ) -> None:
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        if client is not None:
            self.client = client
            return
        import boto3
        from botocore.config import Config

        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def save(self, *, user_id: str, job_id: str, artifact: AdapterArtifact) -> StoredArtifact:
        digest = hashlib.sha256(artifact.data).hexdigest()
        key = f"artifacts/{user_id}/{job_id}/{digest[:16]}-{artifact.filename}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=artifact.data, ContentType=artifact.mime)
        return StoredArtifact(storage_key=key, size=len(artifact.data), sha256=digest)

    def presign_put(self, *, storage_key: str, mime: str, expires_in: int = 900) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": storage_key, "ContentType": mime},
            ExpiresIn=expires_in,
        )

    def presign_get(self, *, storage_key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )

    def public_url(self, storage_key: str) -> str | None:
        if not self.public_base_url:
            return None
        return f"{self.public_base_url}/{quote(storage_key, safe='/')}"
