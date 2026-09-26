"""分片上传的四种请求(Initiate / UploadPart / Complete / Abort),签名和**官方 SDK** 逐字相同。

## 为什么需要这条

分片上传带着一种此前从没签过的参数:**没有值的** `?uploads`。各家对它的规范化不一样 ——
SigV4 系(TOS、S3)写成 `uploads=`,阿里云 V4 **只写名字** `uploads`(alibabacloud-oss-v2 的
`_calc_canonical_request`:值为空就只留键),COS 当作空串值、参数名进 `q-url-param-list`。
写错任何一家,算法全对、串差一个等号,服务端回的都是一句 403。

## 向量从哪来

在一个离线的临时环境里装 alibabacloud-oss-v2 1.4.0 / tos 2.9.3 / cos-python-sdk-v5 1.9.44,
固定时间 2026-09-23T08:00:00Z、假密钥、对象名 `dir/中文 file.mp4`,四种请求的头和正文与插件发的一致:
Initiate 带 `content-type: video/mp4`、空正文;UploadPart 正文 `hello`;Complete 正文见 COMPLETE(TOS 是 JSON);
Abort 什么都不带。OSS 调 `SignerV4().sign`,TOS 调 `Auth._make_signature`(签全部头的模式),
COS 调 `CosS3Auth(expire=900)`(和插件的 REQUEST_TTL 一样)并把 `time.time` 钉在同一刻。
AWS 那一家没在这里:它的 SigV4 和 TOS 同构(`uploads=`),而单签名链路由 AWS 官方向量钉着
(见 test_object_storage_plugin)。
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "object-storage" / "tools"
KEY = "dir/中文 file.mp4"
COS_HEAD = ("q-sign-algorithm=sha1&q-ak=AKIDExampleSecretIdForVectors&q-sign-time=1790150340;1790151300"
            "&q-key-time=1790150340;1790151300")

#: 服务商 → (桶, 地域, AK, SK, {请求: 期望的签名}) —— OSS / TOS 比 Signature= 之后那一段,COS 比整个头。
CASES = {
    "aliyun-oss": ("examplebucket", "cn-hangzhou", "LTAI5tExampleAccessKey", "ExampleSecretKeyForVectorsOnly0000", {
        "initiate": "b8ec9abe2d93674a70d55e27316e2f9193e00926e80718f2e38245f028fd4b0e",
        "part": "aa7a96ea9c66926b488694cd3f6961ac4d8c29d71fe5b2cb73fc65a2853283cd",
        "complete": "0ce8cb7f66cbd740969e5eb4c2557082cd9703e892f6cb639347845af5af2e45",
        "abort": "051055c36a77f2687409c0e7bcc72cf3ee12ccd58e988d03cda02c39dc93b10a",
    }),
    "volcengine-tos": ("examplebucket", "cn-beijing", "AKLTExampleAccessKey", "ExampleSecretKeyForVectorsOnly0000", {
        "initiate": "86789955fb36c172e6b66b7abf613c9ae10baf4fc9dfcdc0a7a22d35d2224a5d",
        "part": "4df32ff4ccf1106398902d1b0cfbd5e90f6dd0308ab102f466d46613c5ab107e",
        "complete": "627b1377d043b6b80eb8663a36a62e280d7d1ab51a564742c94ba0dc9891c3b5",
        "abort": "601dc8da0c2e33a2e6addcfcf0b61cf76b55a45fe2882ce9972b25a396ac1ac8",
    }),
    "tencent-cos": ("examplebucket-1250000000", "ap-guangzhou", "AKIDExampleSecretIdForVectors",
                    "ExampleSecretKeyForVectorsOnly00", {
        "initiate": f"{COS_HEAD}&q-header-list=content-length;content-type;host&q-url-param-list=uploads"
                    "&q-signature=4e298e20565e8148ddecbd7c3dc9fc3fc6554ebf",
        "part": f"{COS_HEAD}&q-header-list=content-length;content-type;host&q-url-param-list=partnumber;uploadid"
                "&q-signature=9feaa8e68fc027da2112cc6bbbb6855faf8b1739",
        "complete": f"{COS_HEAD}&q-header-list=content-length;content-type;host&q-url-param-list=uploadid"
                    "&q-signature=f5a5f60b5465ec1a496c31fb1857af5479155a0c",
        "abort": f"{COS_HEAD}&q-header-list=host&q-url-param-list=uploadid"
                 "&q-signature=3db9d1af40717962108ed9641e0368bff9120bcd",
    }),
}


#: Complete 的正文。**TOS 的原生接口收 JSON**(官方 SDK `tos` 的 to_complete_multipart_upload_request +
#: json.dumps),别家收 XML —— 发错格式,签名全对也是 400。
_XML_DONE = b'<CompleteMultipartUpload><Part><PartNumber>1</PartNumber><ETag>"abc"</ETag></Part></CompleteMultipartUpload>'
COMPLETE = {"aliyun-oss": _XML_DONE, "tencent-cos": _XML_DONE,
            "volcengine-tos": b'{"Parts":[{"PartNumber":1,"ETag":"\\"abc\\""}]}'}


@pytest.fixture
def modules(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(TOOLS))
    try:
        import providers
        import storage
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(storage, "_now", lambda: datetime.datetime(2026, 9, 23, 8, 0, tzinfo=datetime.UTC))
    # 让一个 5 字节的文件也走分片,一片就是它自己 —— 和 SDK 那一侧的 UploadPart 正文一致。
    monkeypatch.setattr(storage, "MULTIPART_THRESHOLD", 0)
    return providers, storage


def _signature(provider: str, header: str) -> str:
    return header if provider == "tencent-cos" else header.split("Signature=")[1]


def _run(modules, provider: str, tmp_path: Path, monkeypatch, sent: list[dict], *, fail_part: bool = False) -> None:
    providers, storage = modules
    bucket_name, region, ak, sk, _ = CASES[provider]

    def fake_request(url, *, method, headers, body=None):
        sent.append({"url": url, "method": method, "headers": headers, "body": body})
        if fail_part and "partNumber" in url:
            raise storage._HttpFailure(403, "<Error><Code>AccessDenied</Code><Message>no</Message></Error>")
        return b"<InitiateMultipartUploadResult><UploadId>up123</UploadId></InitiateMultipartUploadResult>", {
            "etag": '"abc"'}

    monkeypatch.setattr(storage, "_request", fake_request)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"hello")
    bucket = storage.Bucket(provider=providers.PROVIDERS[provider], bucket=bucket_name, region=region, endpoint="",
                            access_key=ak, secret=sk)
    bucket.upload_file(KEY, str(source), content_type="video/mp4", reporter=storage.Reporter(stream=False))


@pytest.mark.parametrize("provider", CASES)
def test_分片上传三步的签名和SDK一致(modules, provider: str, tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []
    _run(modules, provider, tmp_path, monkeypatch, sent)
    expected = CASES[provider][4]

    assert [one["method"] for one in sent] == ["POST", "PUT", "POST"]
    assert sent[0]["url"].endswith("/dir/%E4%B8%AD%E6%96%87%20file.mp4?uploads"), "URL 上没有值的参数只写名字"
    assert sent[1]["url"].endswith("?partNumber=1&uploadId=up123")
    assert sent[2]["body"] == COMPLETE[provider]
    for one, name in zip(sent, ("initiate", "part", "complete")):
        assert _signature(provider, one["headers"]["authorization"]) == expected[name], name


@pytest.mark.parametrize("provider", CASES)
def test_某一片失败就Abort_签名也和SDK一致(modules, provider: str, tmp_path: Path, monkeypatch) -> None:
    """分片留在桶里要收存储费,而且控制台里看不见 —— 失败就 Abort,然后把原来那个错误报出去。"""
    storage = modules[1]
    sent: list[dict] = []
    with pytest.raises(storage.StorageError, match="AccessDenied"):
        _run(modules, provider, tmp_path, monkeypatch, sent, fail_part=True)

    assert [one["method"] for one in sent] == ["POST", "PUT", "DELETE"]
    assert sent[2]["url"].endswith("?uploadId=up123")
    assert _signature(provider, sent[2]["headers"]["authorization"]) == CASES[provider][4]["abort"]
