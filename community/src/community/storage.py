"""对象存储:一个接口,两种实现(ADR 0026 第 6 节)。

- `local`:服务器磁盘上的一个卷。文件由反代直接出(`/community-media/…`,见 deploy/community/Caddyfile),
  上传走服务自己的一个带签名的 PUT 地址。
- `s3`:S3 兼容接口(腾讯云 COS、阿里云 OSS、MinIO、AWS S3)。上传与下载给预签名地址。

**用户上传的东西一律不当网页内联出**:能内联显示的只有白名单里的媒体类型(图片 / 视频 / 音频,没有 SVG、
没有 HTML);插件包、工作流文件等「下载型」文件在 `files/` 下,一律 `Content-Disposition: attachment`。
全站 `X-Content-Type-Options: nosniff`。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from community.config import API_PREFIX, Settings

#: 快照里的媒体、头像、封面允许的类型 → 存储时用的扩展名(反代按扩展名给 Content-Type)。
MEDIA_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/webm": ".weba",
    "audio/flac": ".flac",
}
IMAGE_TYPES = frozenset(key for key in MEDIA_TYPES if key.startswith("image/"))

_KEY_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/")


def check_key(key: str) -> str:
    if not key or key.startswith("/") or ".." in key.split("/") or not set(key) <= _KEY_OK:
        raise ValueError(f"unsafe storage key: {key!r}")
    return key


#: 下载型文件与预览图的类型(按扩展名)。
_OTHER_TYPES = {".json": "application/json", ".zip": "application/zip"}


def media_type_of(name: str) -> str:
    """按扩展名给 Content-Type。认不出的一律 application/octet-stream —— 永远不会被当网页内联。"""
    suffix = Path(name).suffix.lower()
    for content_type, extension in MEDIA_TYPES.items():
        if extension == suffix:
            return content_type
    return _OTHER_TYPES.get(suffix, "application/octet-stream")


def blob_key(sha256: str, content_type: str) -> str:
    return f"blobs/{sha256[:2]}/{sha256}{MEDIA_TYPES.get(content_type, '.bin')}"


def attachment(filename: str) -> str:
    ascii_name = "".join(ch if ch.isascii() and ch not in '\\/:*?"<>|;' else "_" for ch in filename) or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class Storage(ABC):
    """存储接口。`key` 一律是相对路径(`blobs/ab/abcd….png`、`files/plugins/…`)。"""

    #: 上传要不要走服务自己的 PUT 地址(local)。s3 给预签名地址,客户端直传。
    uploads_through_service: bool = False

    @abstractmethod
    def put_file(self, key: str, path: Path, *, content_type: str, disposition: str | None = None) -> None: ...

    def put_bytes(self, key: str, data: bytes, *, content_type: str, disposition: str | None = None) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(data)
            temp = Path(handle.name)
        try:
            self.put_file(key, temp, content_type=content_type, disposition=disposition)
        finally:
            temp.unlink(missing_ok=True)

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    def read_bytes(self, key: str) -> bytes:
        with self.open(key) as handle:
            return handle.read()

    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        with self.open(key) as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def media_url(self, key: str) -> str:
        """内联可看的媒体(图片 / 视频 / 音频)的地址。"""

    @abstractmethod
    def download_url(self, key: str, filename: str) -> str:
        """下载型文件的地址(带 attachment)。"""

    @abstractmethod
    def presigned_put(self, key: str, *, content_type: str, size: int) -> dict[str, Any] | None:
        """直传地址 `{url, headers}`;不支持直传(local)返回 None,由服务自己的 PUT 地址接。"""


class LocalStorage(Storage):
    uploads_through_service = True

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.storage_dir).resolve()
        self.prefix = settings.media_url_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def path_of(self, key: str) -> Path:
        return self._path(key)

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"unsafe storage key: {key!r}")
        return path

    def put_file(self, key: str, path: Path, *, content_type: str, disposition: str | None = None) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.partial-{os.getpid()}")
        shutil.copyfile(path, partial)
        os.replace(partial, target)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def media_url(self, key: str) -> str:
        return f"{self.prefix}/{check_key(key)}"

    def download_url(self, key: str, filename: str) -> str:
        # 反代给 files/ 下的一切加 attachment(见 Caddyfile);文件名就是 key 的最后一段。
        return f"{self.prefix}/{check_key(key)}"

    def presigned_put(self, key: str, *, content_type: str, size: int) -> dict[str, Any] | None:
        return None


class S3Storage(Storage):
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.bucket = settings.s3_bucket
        if client is None:  # pragma: no cover - 真的连对象存储
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint or None,
                region_name=settings.s3_region or None,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": settings.s3_addressing_style}),
            )
        self.client = client

    def put_file(self, key: str, path: Path, *, content_type: str, disposition: str | None = None) -> None:
        extra: dict[str, str] = {"ContentType": content_type}
        if disposition:
            extra["ContentDisposition"] = disposition
        self.client.upload_file(str(path), self.bucket, check_key(key), ExtraArgs=extra)

    def open(self, key: str) -> BinaryIO:
        return self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"]

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=check_key(key))["ContentLength"])
        except ClientError:
            return None

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=check_key(key))

    def media_url(self, key: str) -> str:
        if self.settings.s3_public_url:
            return f"{self.settings.s3_public_url.rstrip('/')}/{check_key(key)}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": check_key(key)},
            ExpiresIn=self.settings.download_url_ttl_seconds,
        )

    def download_url(self, key: str, filename: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": check_key(key), "ResponseContentDisposition": attachment(filename)},
            ExpiresIn=self.settings.download_url_ttl_seconds,
        )

    def presigned_put(self, key: str, *, content_type: str, size: int) -> dict[str, Any] | None:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": check_key(key), "ContentType": content_type},
            ExpiresIn=self.settings.upload_url_ttl_seconds,
        )
        return {"url": url, "headers": {"Content-Type": content_type}}


def make_storage(settings: Settings) -> Storage:
    return S3Storage(settings) if settings.storage == "s3" else LocalStorage(settings)


def service_upload_url(settings: Settings, sha256: str, token: str) -> str:
    return f"{settings.public_url}{API_PREFIX}/uploads/{sha256}?t={quote(token)}"


__all__ = [
    "IMAGE_TYPES",
    "media_type_of",
    "LocalStorage",
    "MEDIA_TYPES",
    "S3Storage",
    "Storage",
    "attachment",
    "blob_key",
    "check_key",
    "make_storage",
    "service_upload_url",
]
