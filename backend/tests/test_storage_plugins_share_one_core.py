"""对象存储插件共用同一份主体(和同一份 SigV4),**拷贝必须字节相同**。

## 为什么需要这条

S3、火山 TOS、阿里云 OSS、腾讯云 COS 的 HTTP 接口是同一套(PUT/GET 对象、列目录),只有签名
方言不同。各写一遍的话,差异会出现在那些平时走不到的地方 —— key 里带中文时的转义、
list 的分页参数、预签名的参数名 —— 而那种差异的表现是 **403**,不是报错。

几个插件是独立可分发的包(各自打包成一个 zip 装到用户机器上),所以 `storage.py`(四家)
和 `sigv4.py`(SigV4 系三家)在各个包里各有一份拷贝。**拷贝不可怕,悄悄漂掉的拷贝才可怕**:
在其中一个包里修了个 bug、另外几个没跟上,而这几个插件平时没人会放在一起看。

腾讯云 COS 的原生签名不是 SigV4 这一系,它带自己的 `qsign.py`,只有它一份,不在这里比。

这条棘轮把"拷贝"变成"一份源码 + 被强制的副本"。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import hashlib
import sys
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "plugins" / "examples"
SIGV4_PLUGINS = ("aws-s3", "volcengine-tos", "aliyun-oss")
STORAGE_PLUGINS = (*SIGV4_PLUGINS, "tencent-cos")
#: 共用文件 → 哪几个包里有它。
SHARED = {"storage.py": STORAGE_PLUGINS, "sigv4.py": SIGV4_PLUGINS}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@pytest.mark.parametrize("filename", SHARED)
def test_各插件里的共用文件字节相同(filename: str) -> None:
    digests = {name: _digest(PLUGINS / name / "tools" / filename) for name in SHARED[filename]}
    assert len(set(digests.values())) == 1, (
        f"{filename} 在几个插件里不一样了 —— 修一处而别处没跟上,表现会是 403 而不是报错:\n  "
        + "\n  ".join(f"{name}: {digest}" for name, digest in digests.items())
    )


def test_每个插件都有自己的方言而不是抄同一份main() -> None:
    """共用的是**主体**,不是全部 —— 各家的端点、配置键、工具名必须是自己的。"""
    mains = {name: (PLUGINS / name / "tools" / "main.py").read_text(encoding="utf-8")
             for name in STORAGE_PLUGINS}
    assert len(set(mains.values())) == len(STORAGE_PLUGINS), "有几个 main.py 变成一样的了"
    assert "dialect=sigv4.AWS" in mains["aws-s3"]
    assert "dialect=sigv4.TOS" in mains["volcengine-tos"]
    assert "dialect=sigv4.OSS" in mains["aliyun-oss"]
    assert "dialect=qsign.COS" in mains["tencent-cos"]


def test_主体不认识任何一种签名() -> None:
    """签名是插件交进来的方言。主体里一旦 `import sigv4`,COS 那个包就跑不起来 —— 它没有那个文件。"""
    source = (PLUGINS / "aws-s3" / "tools" / "storage.py").read_text(encoding="utf-8")
    assert "import sigv4" not in source and "import qsign" not in source


def test_签名对得上AWS官方的测试向量() -> None:
    """**用官方向量验,而不是验"它跑起来了"。** 签名错的表现是 403,而 403 有一百种原因;
    向量对上了才说明链路(规范化请求 → 待签串 → 派生密钥)每一步都没写反。"""
    sys.path.insert(0, str(PLUGINS / "aws-s3" / "tools"))
    try:
        import sigv4
    finally:
        sys.path.pop(0)

    signature = sigv4.authorization(
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
        region="us-east-1", stamp="20130524T000000Z", flavor=sigv4.AWS,
    ).split("Signature=")[1]
    # AWS 文档「Example: GET Object」里给出的那一个。
    assert signature == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"


def test_三家的方言各不相同_而且没有派生错() -> None:
    """阿里云把"算法"那一格叫 `x-oss-signature-version`,另外两家叫 `X-…-Algorithm` ——
    从前缀派生的话会得到一个名字对不上的参数,而服务端只回 403,不会说"参数名不对"。"""
    sys.path.insert(0, str(PLUGINS / "aws-s3" / "tools"))
    try:
        import sigv4
    finally:
        sys.path.pop(0)

    assert sigv4.OSS.query_names["algorithm"] == "x-oss-signature-version"
    assert sigv4.AWS.query_names["algorithm"] == "X-Amz-Algorithm"
    assert sigv4.TOS.query_names["algorithm"] == "X-Tos-Algorithm"
    # 派生链的第一步各不相同:AWS 给密钥加 "AWS4",阿里云加 "aliyun_v4",火山什么都不加。
    assert (sigv4.AWS.prefix, sigv4.TOS.prefix, sigv4.OSS.prefix) == ("AWS4", "", "aliyun_v4")
    # scope 的结尾同理。
    assert (sigv4.AWS.terminator, sigv4.TOS.terminator, sigv4.OSS.terminator) == (
        "aws4_request", "request", "aliyun_v4_request")
    # 阿里云 V4 的**结构**也不同(AdditionalHeaders、只签默认头、URI 带桶名)—— 只有它开这个开关。
    # 光有这几行名字对不上的断言是不够的:名字全对、结构错,照样 400。结构由
    # test_oss_signature_matches_the_sdk 拿官方 SDK 的向量钉住。
    assert sigv4.OSS.aliyun_v4 and not sigv4.AWS.aliyun_v4 and not sigv4.TOS.aliyun_v4
    assert "signed_headers" not in sigv4.OSS.query_names


def test_对象存储插件都在市场索引里() -> None:
    """索引由 scripts/sync-plugin-registry.py 生成 —— 漏同步的话,用户在装之前看到的就是旧的那份。"""
    import json

    registry = json.loads(
        (PLUGINS.parents[1] / "website" / "public" / "plugins" / "registry.json").read_text(encoding="utf-8")
    )
    items = registry["plugins"] if isinstance(registry, dict) else registry
    ids = {item.get("id") for item in items}
    for name in STORAGE_PLUGINS:
        assert f"dev.mosael.{name}" in ids, f"{name} 没进市场索引"
