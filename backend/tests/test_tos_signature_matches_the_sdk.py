"""火山 TOS 的签名和**官方 SDK** 在同样输入下逐字相同。

阿里云那一路此前从没对照过官方实现,一连就 400(见 test_oss_signature_matches_the_sdk);
TOS 是同一个空白 —— 只是它恰好按 SigV4 的结构签,没出事。这里把它也钉住。

向量来自火山官方 Python SDK `tos` 的 `auth.Auth`:固定时间 20260923T080000Z、假密钥,
直接调它的 `_make_signature`(公开的 sign_request / sign_url 取的是当前时间,没法固定)。
上传那一条用它「签全部头」的模式 —— 我们连 content-length 一起签,服务端按我们报的
SignedHeaders 重算,这两种都对。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "volcengine-tos" / "tools"
KEY = "dir/中文 file.mp4"
CRED = "Credential=AKLTExampleAccessKey/20260923/cn-beijing/tos/request"

SDK_LIST = (f"TOS4-HMAC-SHA256 {CRED}, SignedHeaders=host;x-tos-content-sha256;x-tos-date, "
            "Signature=59cee75f1b3d65b0ec6ed139f733c67e73bb33284252e010bf2cdf942f93847d")
SDK_PUT = (f"TOS4-HMAC-SHA256 {CRED}, SignedHeaders=content-length;content-type;host;x-tos-content-sha256;x-tos-date, "
           "Signature=79deebb30c03f524e04b0cfb0d548230b3f9daba47541153baf8d1a238bf5b4d")
SDK_PRESIGN_SIGNATURE = "5e3584c933903abe2f4dba0c5b165bb61d7844b5ea26eac8dc073b1426beab4f"


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(TOOLS))
    try:
        import sigv4
        import storage
    finally:
        sys.path.pop(0)
    sent: list[dict] = []
    monkeypatch.setattr(storage, "_stamp", lambda: "20260923T080000Z")
    monkeypatch.setattr(storage, "_request",
                        lambda url, *, method, headers, body=None: (sent.append(headers), b"<ListBucketResult/>")[1])
    one = storage.Bucket(flavor=sigv4.TOS, endpoint="tos-cn-beijing.volces.com", bucket="examplebucket",
                         region="cn-beijing", access_key="AKLTExampleAccessKey",
                         secret="ExampleSecretKeyForVectorsOnly0000")
    return one, sent


def test_列目录的签名头和SDK一致(bucket) -> None:
    one, sent = bucket
    one.listing("a/中", 10)
    assert sent[0]["authorization"] == SDK_LIST


def test_上传的签名头和SDK一致(bucket) -> None:
    one, sent = bucket
    one.put(KEY, b"hello", content_type="video/mp4")
    assert sent[0]["authorization"] == SDK_PUT


def test_预签名的签名和SDK一致(bucket) -> None:
    one, _ = bucket
    assert one.presign(KEY, expires=3600).endswith(f"X-Tos-Signature={SDK_PRESIGN_SIGNATURE}")
