"""阿里云 OSS 的 V4 签名,和**官方 SDK** 在同样输入下算出的逐字相同。

## 为什么需要这条

这份签名代码此前只用 AWS 官方向量验过(test_storage_plugins_share_one_core)。阿里云那一路
换了算法名、日期头、派生前缀 —— 看上去"同源",于是没人单独验。真机一连就是:

    400 Unknown parameter in Authorization header.

阿里云 V4 的**结构**和 SigV4 不同:只签 x-oss-* / content-type / content-md5、那一行是
AdditionalHeaders 不是 SignedHeaders、Authorization 里没有 SignedHeaders、规范化 URI 带桶名。
只换名字不改结构,算法全对也签不上。

## 向量从哪来

alibabacloud-oss-v2 1.4.0 的 `SignerV4`,固定时间 2026-09-23T08:00:00Z、假密钥,三个场景:
列目录(前缀带中文)、上传(对象名带中文和空格)、预签名。生成脚本的做法:构造 HttpRequest +
SigningContext(product="oss", region, bucket, key, signing_time),调 `SignerV4().sign`。
对象名带中文和空格是有意的 —— 规范化 URI 的转义是最容易差一个字符的地方。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "aliyun-oss" / "tools"

AK, SK = "LTAI5tExampleAccessKey", "ExampleSecretKeyForVectorsOnly0000"
KEY = "dir/中文 file.mp4"
SCOPE = "LTAI5tExampleAccessKey/20260923/cn-hangzhou/oss/aliyun_v4_request"

SDK_LIST = f"OSS4-HMAC-SHA256 Credential={SCOPE},Signature=ef3f01c47c81c9d9a181114b49cc3b05d3673558ff67fbb7914cc94d42a560c6"
SDK_PUT = f"OSS4-HMAC-SHA256 Credential={SCOPE},Signature=2f2ce6f40e0c7447cb4fb031c2bb59075c1548b100f5823485c252355c579d41"
SDK_PRESIGN_SIGNATURE = "a8bb474b3a1eec3dab279e2a7c44ee69d11fad229991f19ac9cb2d5aa08a8164"


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(TOOLS))
    try:
        import sigv4
        import storage
    finally:
        sys.path.pop(0)
    sent: list[dict] = []

    def fake_request(url, *, method, headers, body=None):
        sent.append({"url": url, "method": method, "headers": headers})
        return b'<?xml version="1.0"?><ListBucketResult></ListBucketResult>'

    monkeypatch.setattr(storage, "_stamp", lambda: "20260923T080000Z")
    monkeypatch.setattr(storage, "_request", fake_request)
    one = storage.Bucket(flavor=sigv4.OSS, endpoint="oss-cn-hangzhou.aliyuncs.com", bucket="examplebucket",
                         region="cn-hangzhou", access_key=AK, secret=SK)
    return one, sent


def test_列目录的签名头和SDK一致(bucket) -> None:
    one, sent = bucket
    one.listing("a/中", 10)

    assert sent[0]["headers"]["authorization"] == SDK_LIST


def test_上传的签名头和SDK一致(bucket) -> None:
    one, sent = bucket
    one.put(KEY, b"hello", content_type="video/mp4")

    assert sent[0]["headers"]["authorization"] == SDK_PUT


def test_预签名直链和SDK一致(bucket) -> None:
    """参数顺序可以不同(服务端按规范化规则重排),签名和参数集合必须一致。"""
    one, _ = bucket
    url = one.presign(KEY, expires=3600)

    path, _, query = url.partition("?")
    assert path == "https://examplebucket.oss-cn-hangzhou.aliyuncs.com/dir/%E4%B8%AD%E6%96%87%20file.mp4"
    params = dict(pair.split("=", 1) for pair in query.split("&"))
    assert params == {
        "x-oss-signature-version": "OSS4-HMAC-SHA256",
        "x-oss-date": "20260923T080000Z",
        "x-oss-expires": "3600",
        "x-oss-credential": "LTAI5tExampleAccessKey%2F20260923%2Fcn-hangzhou%2Foss%2Faliyun_v4_request",
        "x-oss-signature": SDK_PRESIGN_SIGNATURE,
    }
