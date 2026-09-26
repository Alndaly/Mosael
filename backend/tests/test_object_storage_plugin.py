"""对象存储是**一个插件、五个服务商选项**,各家的差异只住在 providers.py 那一张表里。

此前是四个插件包(阿里云 OSS / 腾讯云 COS / 火山引擎 TOS / Amazon S3),`storage.py` 和 `sigv4.py`
在包之间逐字节拷贝、靠一条棘轮钉着不漂 —— 差异其实只有「签名方言、默认接入点、预签名上限、寻址方式」
那一张表(providers.py)。这里钉住那张表,以及这次一起修掉的几个 bug:

- 默认对象键是 `mosael/<文件名>`:两份都叫 image.png 的素材互相覆盖,而宿主按素材缓存着前一份的直链;
- 上传把整个文件读进内存、一次 PUT,没有声明预算(默认 60 秒)—— 大一点的成片必然超时;
- 预签名有效期不看各家上限(SigV4 系最长 7 天),给错了只剩一句 `ValueError`;
- 失败只回一句原始 XML 里的 Message:桶在别的地域时用户看不出该改哪一格;
- 列目录只有第一页。

签名链路本身由官方 SDK 的向量钉着(test_*_signature_matches_the_sdk、
test_object_storage_multipart_matches_the_sdk)。**不连任何真的云** —— 请求全部换成假的。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import datetime
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "bundled" / "object-storage"
TOOLS = PLUGIN / "tools"


@pytest.fixture
def m(monkeypatch: pytest.MonkeyPatch):
    """插件的几个模块。请求默认换成一个会记账的假服务端(`m.sent` / `m.replies`)。"""
    sys.path.insert(0, str(TOOLS))
    try:
        import main
        import providers
        import sigv4
        import storage
    finally:
        sys.path.pop(0)

    class Kit:
        pass

    kit = Kit()
    kit.main, kit.providers, kit.sigv4, kit.storage = main, providers, sigv4, storage
    kit.sent, kit.replies = [], []

    def fake_request(url, *, method, headers, body=None):
        kit.sent.append({"url": url, "method": method, "headers": headers, "body": body})
        reply = kit.replies.pop(0) if kit.replies else (b"<Ok><UploadId>up1</UploadId></Ok>", {"etag": '"e"'})
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(storage, "_request", fake_request)
    monkeypatch.setattr(storage, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(storage, "_now", lambda: datetime.datetime(2026, 9, 23, 8, 0, tzinfo=datetime.UTC))
    kit.bucket = lambda provider="aliyun-oss", **kw: storage.Bucket(
        provider=providers.PROVIDERS[provider], bucket=kw.get("bucket", "b"), region=kw.get("region", "r1"),
        endpoint=kw.get("endpoint", ""), access_key="ak", secret="sk", locale=kw.get("locale", "zh"))
    return kit


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    base = {"STORAGE_PROVIDER": "aliyun-oss", "STORAGE_BUCKET": "b", "STORAGE_REGION": "cn-hangzhou",
            "STORAGE_ENDPOINT": "", "STORAGE_ACCESS_KEY_ID": "ak", "STORAGE_ACCESS_KEY_SECRET": "sk"}
    for key, value in {**base, **values}.items():
        monkeypatch.setenv(key, value)


# —— 服务商那张表 ————————————————————————————————————————————————


@pytest.mark.parametrize(("provider", "region", "host"), [
    ("aliyun-oss", "cn-hangzhou", "b.oss-cn-hangzhou.aliyuncs.com"),
    ("tencent-cos", "ap-guangzhou", "b.cos.ap-guangzhou.myqcloud.com"),
    ("volcengine-tos", "cn-beijing", "b.tos-cn-beijing.volces.com"),
    ("aws-s3", "us-east-1", "b.s3.us-east-1.amazonaws.com"),
])
def test_接入点留空时按各家的规则拼(m, provider: str, region: str, host: str) -> None:
    bucket = m.bucket(provider, region=region)
    assert bucket.presign("a.mp4").startswith(f"https://{host}/a.mp4?")


def test_S3兼容服务走路径式_认明写的http(m) -> None:
    """本机的 MinIO 多半没证书、也没给桶配泛域名:`https://b.localhost:9000` 两样都连不上。"""
    bucket = m.bucket("s3-compatible", region="us-east-1", endpoint="http://localhost:9000")
    assert bucket.presign("dir/a.mp4").startswith("http://localhost:9000/b/dir/a.mp4?X-Amz-Algorithm=")
    bucket.listing()
    assert m.sent[-1]["url"].startswith("http://localhost:9000/b?")
    assert m.sent[-1]["headers"]["host"] == "localhost:9000"


def test_S3兼容服务不填接入点_当场说清楚(m) -> None:
    with pytest.raises(m.storage.StorageError, match="接入点"):
        m.bucket("s3-compatible", endpoint="")


def test_签名对得上AWS官方的测试向量(m) -> None:
    """**用官方向量验,而不是验"它跑起来了"。** 签名错的表现是 403,而 403 有一百种原因。"""
    signature = m.sigv4.authorization(
        method="GET", path="/test.txt", query="",
        headers={
            "host": "examplebucket.s3.amazonaws.com",
            "range": "bytes=0-9",
            "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "x-amz-date": "20130524T000000Z",
        },
        payload_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1", stamp="20130524T000000Z", flavor=m.sigv4.AWS,
    ).split("Signature=")[1]
    # AWS 文档「Example: GET Object」里给出的那一个。
    assert signature == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"


def test_三家SigV4方言各不相同_而且没有派生错(m) -> None:
    """阿里云把"算法"那一格叫 `x-oss-signature-version`,另外两家叫 `X-…-Algorithm` ——
    从前缀派生的话会得到一个名字对不上的参数,而服务端只回 403,不会说"参数名不对"。"""
    sigv4 = m.sigv4
    assert sigv4.OSS.query_names["algorithm"] == "x-oss-signature-version"
    assert sigv4.AWS.query_names["algorithm"] == "X-Amz-Algorithm"
    assert sigv4.TOS.query_names["algorithm"] == "X-Tos-Algorithm"
    assert (sigv4.AWS.prefix, sigv4.TOS.prefix, sigv4.OSS.prefix) == ("AWS4", "", "aliyun_v4")
    assert (sigv4.AWS.terminator, sigv4.TOS.terminator, sigv4.OSS.terminator) == (
        "aws4_request", "request", "aliyun_v4_request")
    assert sigv4.OSS.aliyun_v4 and not sigv4.AWS.aliyun_v4 and not sigv4.TOS.aliyun_v4


def test_主体不认识任何一家() -> None:
    """差异只许住在 providers.py 那张表里 —— 主体里一旦出现某一家的名字,就又开始长分支了。"""
    source = (TOOLS / "storage.py").read_text(encoding="utf-8")
    assert "import sigv4" not in source and "import qsign" not in source
    # 按「是哪一家」分支(`if provider.id == ...`)就是差异漏出了那张表。
    assert "provider.id" not in source and ".aliyuncs.com" not in source


# —— 预签名有效期 ————————————————————————————————————————————————


@pytest.mark.parametrize(("provider", "asked", "signed"), [
    ("aliyun-oss", 30 * 86400, 604800),
    ("volcengine-tos", 30 * 86400, 604800),
    ("aws-s3", 30 * 86400, 604800),
    ("tencent-cos", 30 * 86400, 30 * 86400),  # COS 的 KeyTime 没有官方上限
    ("aliyun-oss", None, 3600),
])
def test_有效期超过这一家的上限就按上限签_如实交回(m, provider, asked, signed) -> None:
    assert m.bucket(provider).clamp_expires(asked) == signed


@pytest.mark.parametrize("asked", ["一小时", 0, -5])
def test_有效期给错了_说一句人话而不是ValueError(m, asked) -> None:
    with pytest.raises(m.storage.StorageError, match="有效期"):
        m.bucket().clamp_expires(asked)


def test_presign工具交回的是真正签的有效期(m, monkeypatch) -> None:
    _env(monkeypatch)
    out = m.main.presign({"key": "a.mp4", "expires": 99 * 86400}, "zh", m.storage.Reporter(stream=False))
    assert out["expires_in"] == 604800
    assert "x-oss-expires=604800" in out["url"]


# —— 上传 ——————————————————————————————————————————————————————


def test_默认对象键带内容指纹_同名的两份素材不互相覆盖(m, monkeypatch, tmp_path) -> None:
    """此前默认键是 `mosael/<文件名>`:第二份 image.png 覆盖第一份,而宿主按素材缓存着第一份的直链 ——
    那条链接从此下到的是另一张图。"""
    _env(monkeypatch)
    first, second = tmp_path / "1" / "image.png", tmp_path / "2" / "image.png"
    for path, data in ((first, b"one"), (second, b"two")):
        path.parent.mkdir()
        path.write_bytes(data)
    reporter = m.storage.Reporter(stream=False)

    a = m.main.upload({"asset_id": str(first)}, "zh", reporter)["key"]
    b = m.main.upload({"asset_id": str(second)}, "zh", reporter)["key"]
    again = m.main.upload({"asset_id": str(first)}, "zh", reporter)["key"]

    assert a != b, "同名不同内容落在了同一个键上"
    assert a == again, "同样的内容应该落在同一个键上(重传是幂等的)"
    assert a.startswith("mosael/") and a.endswith("/image.png")


def test_小文件一次PUT_带对的ContentType(m, tmp_path) -> None:
    source = tmp_path / "clip.mov"
    source.write_bytes(b"x" * 10)
    m.bucket().upload_file("k/clip.mov", str(source), content_type="video/quicktime",
                           reporter=m.storage.Reporter(stream=False))
    assert [one["method"] for one in m.sent] == ["PUT"]
    assert m.sent[0]["headers"]["content-type"] == "video/quicktime"
    assert m.sent[0]["body"] == b"x" * 10


def test_大文件分片上传_边传边报进度(m, monkeypatch, tmp_path, capsys) -> None:
    """此前整个文件读进内存、一次 PUT,也没有声明预算(默认 60 秒)。"""
    monkeypatch.setattr(m.storage, "MULTIPART_THRESHOLD", 8)
    monkeypatch.setattr(m.storage, "PART_BYTES", 4)
    source = tmp_path / "big.mp4"
    source.write_bytes(b"0123456789")  # 4 + 4 + 2

    m.bucket().upload_file("big.mp4", str(source), content_type="video/mp4", reporter=m.storage.Reporter(stream=True))

    assert [one["method"] for one in m.sent] == ["POST", "PUT", "PUT", "PUT", "POST"]
    assert [one["body"] for one in m.sent[1:4]] == [b"0123", b"4567", b"89"]
    assert b"<PartNumber>3</PartNumber>" in m.sent[-1]["body"]
    events = [json.loads(one) for one in capsys.readouterr().out.splitlines()]
    assert [event["event"] for event in events] == ["progress"] * 3
    assert events[-1]["progress"] == 1.0


def test_片数不够时放大片大小(m, monkeypatch, tmp_path) -> None:
    """四家都是最多 10000 片:片大小不跟着文件放大的话,超过 160GB 的文件第 10001 片直接被拒。"""
    monkeypatch.setattr(m.storage, "MULTIPART_THRESHOLD", 1)
    monkeypatch.setattr(m.storage, "PART_BYTES", 1)
    monkeypatch.setattr(m.storage, "MAX_PARTS", 2)
    source = tmp_path / "big.mp4"
    source.write_bytes(b"abcde")
    m.bucket().upload_file("big.mp4", str(source), content_type="video/mp4", reporter=m.storage.Reporter(stream=False))
    assert [one["body"] for one in m.sent if one["method"] == "PUT"] == [b"abc", b"de"]


def test_取消时停在片与片之间_并Abort(m, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(m.storage, "MULTIPART_THRESHOLD", 1)
    monkeypatch.setattr(m.storage, "PART_BYTES", 2)
    cancel = tmp_path / "cancel"
    monkeypatch.setenv("MOSAEL_PLUGIN_CANCEL_FILE", str(cancel))
    source = tmp_path / "big.mp4"
    source.write_bytes(b"abcdef")
    reporter = m.storage.Reporter(stream=False)
    original = reporter.progress
    reporter.progress = lambda fraction, message: (cancel.write_text("1"), original(fraction, message))

    with pytest.raises(m.storage.Cancelled):
        m.bucket().upload_file("big.mp4", str(source), content_type="video/mp4", reporter=reporter)
    assert [one["method"] for one in m.sent] == ["POST", "PUT", "DELETE"], "取消后还在传,或者没有 Abort"


def test_Complete在200里带着错误_不当成功(m, monkeypatch, tmp_path) -> None:
    """S3 的 CompleteMultipartUpload 合并到一半失败时,回的是 **200** 加一个 <Error> 正文。"""
    monkeypatch.setattr(m.storage, "MULTIPART_THRESHOLD", 1)
    source = tmp_path / "big.mp4"
    source.write_bytes(b"ab")
    m.replies.extend([
        (b"<InitiateMultipartUploadResult><UploadId>u</UploadId></InitiateMultipartUploadResult>", {}),
        (b"", {"etag": '"e1"'}),
        (b"<Error><Code>InternalError</Code><Message>merge failed</Message></Error>", {}),
    ])
    with pytest.raises(m.storage.StorageError, match="merge failed"):
        m.bucket().upload_file("big.mp4", str(source), content_type="video/mp4", reporter=m.storage.Reporter(stream=False))
    assert m.sent[-1]["method"] == "DELETE"


# —— 重试与错误翻译 ——————————————————————————————————————————————


def _failure(m, status: int, code: str, **extra: str):
    body = "".join(f"<{k}>{v}</{k}>" for k, v in {"Code": code, "Message": "msg", **extra}.items())
    return m.storage._HttpFailure(status, f"<Error>{body}</Error>")


def test_限流和服务端临时错误_重签重试(m) -> None:
    m.replies.extend([_failure(m, 503, "SlowDown"), _failure(m, 500, "InternalError")])
    m.bucket().listing()
    assert len(m.sent) == 3


def test_没权限不重试(m) -> None:
    m.replies.append(_failure(m, 403, "AccessDenied"))
    with pytest.raises(m.storage.StorageError, match="没有这个桶的权限"):
        m.bucket().listing()
    assert len(m.sent) == 1


def test_桶在别的地域_点名该填哪个地域(m) -> None:
    """S3 的原话是 `the region 'us-east-1' is wrong; expecting 'eu-west-1'`,错误体里带着 <Region>。"""
    m.replies.append(_failure(m, 400, "AuthorizationHeaderMalformed", Region="eu-west-1"))
    with pytest.raises(m.storage.StorageError) as caught:
        m.bucket("aws-s3", region="us-east-1").listing()
    assert "eu-west-1" in str(caught.value) and "地域" in str(caught.value)


def test_阿里云要求换接入点_点名是哪个(m) -> None:
    """阿里云:`The bucket you are attempting to access must be addressed using the specified endpoint`。"""
    m.replies.append(_failure(m, 403, "AccessDenied", Endpoint="oss-cn-shanghai.aliyuncs.com"))
    with pytest.raises(m.storage.StorageError, match="oss-cn-shanghai.aliyuncs.com"):
        m.bucket(region="cn-hangzhou").listing()


def test_错误按调用方的语言说(m) -> None:
    m.replies.append(_failure(m, 404, "NoSuchBucket"))
    with pytest.raises(m.storage.StorageError, match="does not exist"):
        m.bucket(locale="en").listing()


# —— 列目录 ——————————————————————————————————————————————————————


def test_列目录翻页_V2用continuation_token(m) -> None:
    m.replies.append((b"<ListBucketResult><Contents><Key>a</Key><Size>1</Size></Contents>"
                      b"<IsTruncated>true</IsTruncated><NextContinuationToken>tok</NextContinuationToken>"
                      b"</ListBucketResult>", {}))
    items, following = m.bucket().listing("p/", 1)
    assert [one["key"] for one in items] == ["a"] and following == "tok"

    m.bucket().listing("p/", 1, following)
    assert "continuation-token=tok" in m.sent[-1]["url"] and "list-type=2" in m.sent[-1]["url"]


def test_火山TOS的正文是JSON_列目录和报错都认(m) -> None:
    """TOS 原生接口的列目录、分片、错误体都是 JSON(官方 SDK `tos` 用 json.loads 读)。此前一律按 XML 解,
    TOS 的列目录直接崩成一句 `ParseError`。"""
    m.replies.append((json.dumps({"Name": "b", "Contents": [{"Key": "a.mp4", "Size": 3, "LastModified": "t"}],
                                  "IsTruncated": True, "NextContinuationToken": "tok"}).encode(), {}))
    items, following = m.bucket("volcengine-tos", region="cn-beijing").listing()
    assert items == [{"key": "a.mp4", "size": 3, "last_modified": "t"}] and following == "tok"

    m.replies.append(m.storage._HttpFailure(404, json.dumps({"Code": "NoSuchBucket", "Message": "gone", "EC": "0006-1"})))
    with pytest.raises(m.storage.StorageError, match="不存在"):
        m.bucket("volcengine-tos", region="cn-beijing").listing()


def test_XML里只有一个对象时也列得出来(m) -> None:
    m.replies.append((b"<ListBucketResult><Contents><Key>only</Key><Size>1</Size></Contents></ListBucketResult>", {}))
    items, following = m.bucket().listing()
    assert [one["key"] for one in items] == ["only"] and following == ""


def test_COS只有V1_没给NextMarker时从最后一个键接着列(m) -> None:
    m.replies.append((b"<ListBucketResult><Contents><Key>a/1</Key><Size>1</Size></Contents>"
                      b"<IsTruncated>true</IsTruncated></ListBucketResult>", {}))
    _items, following = m.bucket("tencent-cos").listing("", 1)
    assert following == "a/1"
    m.bucket("tencent-cos").listing("", 1, following)
    assert "marker=a%2F1" in m.sent[-1]["url"] and "list-type" not in m.sent[-1]["url"]


def test_fetch交回地址由宿主搬字节_不收目录(m, monkeypatch) -> None:
    _env(monkeypatch)
    out = m.main.fetch({"key": "dir/中文.mp4"}, "zh", m.storage.Reporter(stream=False))
    assert out["artifact"]["filename"] == "中文.mp4"
    assert out["artifact"]["url"].startswith("https://b.oss-cn-hangzhou.aliyuncs.com/dir/%E4%B8%AD%E6%96%87.mp4?")
    with pytest.raises(m.storage.StorageError):
        m.main.fetch({"key": "dir/"}, "zh", m.storage.Reporter(stream=False))


def test_上传工具按流式协议说话_最后一行是结果(m, monkeypatch, tmp_path) -> None:
    """进度一行一个,最后一行是 {"ok": true, ...}(docs/PLUGIN_MANIFEST 的「流式工具」)。"""
    _env(monkeypatch)
    source = tmp_path / "a.mp4"
    source.write_bytes(b"hi")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool": "storage_upload", "input": {"asset_id": str(source)}, "locale": "en"})))
    out = io.StringIO()
    with redirect_stdout(out):
        m.storage.run({"storage_upload": m.main.upload}, streaming=frozenset({"storage_upload"}))
    lines = [json.loads(one) for one in out.getvalue().splitlines()]
    assert lines[0]["event"] == "progress"
    assert lines[-1]["ok"] is True and lines[-1]["output"]["summary"].startswith("Uploaded to oss://b/mosael/")


# —— 清单 ——————————————————————————————————————————————————————


def _manifest():
    from app.domain.plugins.manifest import parse

    raw = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
    raw["_path"] = str(PLUGIN)
    return parse(raw, str(PLUGIN))


def test_清单_上传对外有后果_流式并声明预算_拉回和只读的不问人() -> None:
    from app.domain.effects import plugin_tool_effects

    manifest = _manifest()
    tools = {tool["name"]: tool for tool in manifest.declared_tools}
    effects = {
        name: plugin_tool_effects(read_only=tool.get("read_only") is True, declared=tool.get("effects"), default=None)
        for name, tool in tools.items()
    }
    assert effects == {"storage_upload": "external", "storage_presign": "none", "storage_fetch": "none",
                       "storage_list": "none"}
    assert tools["storage_upload"]["stream"] is True and tools["storage_upload"]["timeout_seconds"] == 1800
    assert manifest.provides == ["public_url"] and manifest.tool_providing("public_url") == "storage_upload"


def test_清单_连接名沿用老插件的写法() -> None:
    """老连接叫「阿里云 OSS · 桶名」。新模板按服务商渲染出同一个名字,迁过来的连接名字照旧跟着配置走。"""
    from app.domain.plugins.manifest import render_name

    manifest = _manifest()
    assert render_name(manifest, {"STORAGE_PROVIDER": "aliyun-oss", "STORAGE_BUCKET": "mosael"}) == "阿里云 OSS · mosael"
    assert render_name(manifest, {"STORAGE_PROVIDER": "volcengine-tos", "STORAGE_BUCKET": "x"}) == "火山引擎 TOS · x"
    main_source = (TOOLS / "main.py").read_text(encoding="utf-8")
    for option in manifest.field_for("STORAGE_PROVIDER").options:
        assert option["value"] in (TOOLS / "providers.py").read_text(encoding="utf-8"), option
    assert "STORAGE_PROVIDER" in main_source


def test_市场索引里只剩一个对象存储_随应用内置() -> None:
    """索引由 scripts/sync-plugin-registry.py 生成 —— 漏同步的话,市场里还挂着四个已经不存在的包。"""
    registry = json.loads((ROOT / "website" / "public" / "plugins" / "registry.json").read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in registry["plugins"]}
    assert entries["dev.mosael.object-storage"]["bundled"] is True
    for gone in ("aliyun-oss", "aws-s3", "tencent-cos", "volcengine-tos"):
        assert f"dev.mosael.{gone}" not in entries, gone
