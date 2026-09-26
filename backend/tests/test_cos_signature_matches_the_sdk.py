"""腾讯云 COS 的签名和**官方 SDK** 在同样输入下逐字相同。

COS 的原生签名(`q-sign-algorithm=sha1`)和另外三家的 SigV4 不是一系,插件带自己的方言
(plugins/bundled/object-storage/tools/qsign.py)。没法拿真桶验,就拿官方实现验:签错的表现是
403,而 403 有一百种原因;向量对上了,才说明路径原文、键小写、值转义、末尾换行、
SHA1 套 HMAC 这几步一步都没写反。

向量来自官方 Python SDK `cos-python-sdk-v5` 的 `CosS3Auth` / `get_presigned_url`:
把它的 `time.time` 固定在 2026-09-23T08:00:00Z(1790150400)、假密钥。
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "object-storage" / "tools"
KEY = "dir/中文 file.mp4"
HEAD = "q-sign-algorithm=sha1&q-ak=AKIDExampleSecretIdForVectors&q-sign-time=1790150340;1790151300&q-key-time=1790150340;1790151300"

SDK_PUT = f"{HEAD}&q-header-list=content-length;content-type;host&q-url-param-list=&q-signature=686f3f2bbfabf970fda9316f850cf77c91a60451"
SDK_LIST = f"{HEAD}&q-header-list=host&q-url-param-list=max-keys;prefix&q-signature=ba52eee209e3131241236291d1b22d5638cc74de"
SDK_PRESIGNED = (
    "https://examplebucket-1250000000.cos.ap-guangzhou.myqcloud.com/dir/%E4%B8%AD%E6%96%87%20file.mp4"
    "?q-sign-algorithm=sha1&q-ak=AKIDExampleSecretIdForVectors&q-sign-time=1790150340%3B1790154000"
    "&q-key-time=1790150340%3B1790154000&q-header-list=host&q-url-param-list="
    "&q-signature=e7ed5c93f1e723c3052bb28babc948f8ac9ee4f2"
)


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(TOOLS))
    try:
        import providers
        import storage
    finally:
        sys.path.pop(0)
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(storage, "_now", lambda: datetime.datetime(2026, 9, 23, 8, 0, tzinfo=datetime.UTC))
    monkeypatch.setattr(storage, "_request",
                        lambda url, *, method, headers, body=None: (sent.append((url, headers)), (b"<ListBucketResult/>", {"etag": '"abc"'}))[1])
    one = storage.Bucket(provider=providers.PROVIDERS["tencent-cos"], endpoint="",
                         bucket="examplebucket-1250000000", region="ap-guangzhou",
                         access_key="AKIDExampleSecretIdForVectors", secret="ExampleSecretKeyForVectorsOnly00")
    return one, sent


def test_上传的签名头和SDK一致(bucket) -> None:
    one, sent = bucket
    one.put(KEY, b"hello", content_type="video/mp4")
    url, headers = sent[0]
    assert headers["authorization"] == SDK_PUT
    assert url.endswith("/dir/%E4%B8%AD%E6%96%87%20file.mp4"), "签的是原文路径,发的是转义后的"


def test_列目录走V1_签名和SDK一致(bucket) -> None:
    """COS 只有 V1 的 GET Bucket;带上 `list-type=2` 的话它进了签名、服务端却不认。"""
    one, sent = bucket
    one.listing("a/中", 10)
    url, headers = sent[0]
    assert headers["authorization"] == SDK_LIST
    assert "list-type" not in url


def test_预签名直链和SDK一致(bucket) -> None:
    one, _ = bucket
    assert one.presign(KEY, expires=3600) == SDK_PRESIGNED
