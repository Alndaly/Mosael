"""AWS Signature V4 —— **纯标准库**。

插件进程里没有 boto3,也不该有:插件是按 stdio 协议跑的短命脚本,装一整个 SDK 只为签四个
请求,代价是安装体积、版本冲突,以及一条我们控制不了的供应链。SigV4 本身是一页纸的算法。

三家对象存储(S3 / 火山 TOS / 阿里云 OSS)的签名**同源但不同字**:算法名、日期头、
scope 的结尾、密钥派生链的第一步各不相同。所以这一份写成可参数化的,三个插件各传各的 ——
而不是三份各抄一遍(抄出来的那两份迟早在某一处漂掉,而漂掉的表现是 403,不是报错)。
"""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from dataclasses import dataclass

UNSIGNED = "UNSIGNED-PAYLOAD"


@dataclass(frozen=True)
class Flavor:
    """一家对象存储的签名方言。"""

    algorithm: str          # "AWS4-HMAC-SHA256" / "TOS4-HMAC-SHA256" / "OSS4-HMAC-SHA256"
    prefix: str             # 派生链第一步给 secret 加的前缀:"AWS4" / "" / "aliyun_v4"
    service: str            # "s3" / "tos" / "oss"
    terminator: str         # scope 结尾:"aws4_request" / "request" / "aliyun_v4_request"
    date_header: str        # "x-amz-date" / "x-tos-date" / "x-oss-date"
    sha_header: str         # "x-amz-content-sha256" / ...
    #: 预签名 URL 的查询参数名。**不是从前缀派生的** —— 阿里云把"算法"那一格叫
    #: `x-oss-signature-version`,而另外两家叫 `X-…-Algorithm`。派生的话会得到一个名字
    #: 对不上的参数,而服务端只会回 403,不会说"你这个参数名不对"。
    query_names: "dict[str, str]"
    #: 阿里云在规范化请求里**多一行** `AdditionalHeaders`(即使为空也要占一行)。少这一行
    #: 或多这一行,服务端算出来的都是另一个签名 —— 表现是 403,而不是"格式不对"。
    additional_headers_line: bool = False
    #: 阿里云的 `x-oss-content-sha256` 目前**只收 `UNSIGNED-PAYLOAD`**(文档原话),
    #: 所以那一家不签正文哈希。
    unsigned_payload_only: bool = False


def _amz_style(prefix: str) -> dict[str, str]:
    return {
        "algorithm": f"{prefix}Algorithm", "credential": f"{prefix}Credential",
        "date": f"{prefix}Date", "expires": f"{prefix}Expires",
        "signed_headers": f"{prefix}SignedHeaders", "signature": f"{prefix}Signature",
    }


AWS = Flavor("AWS4-HMAC-SHA256", "AWS4", "s3", "aws4_request", "x-amz-date",
             "x-amz-content-sha256", _amz_style("X-Amz-"))
TOS = Flavor("TOS4-HMAC-SHA256", "", "tos", "request", "x-tos-date",
             "x-tos-content-sha256", _amz_style("X-Tos-"))
#: 阿里云自成一套(文档原话里那几个名字):算法那一格叫 `x-oss-signature-version`。
OSS = Flavor(
    "OSS4-HMAC-SHA256", "aliyun_v4", "oss", "aliyun_v4_request", "x-oss-date", "x-oss-content-sha256",
    {"algorithm": "x-oss-signature-version", "credential": "x-oss-credential", "date": "x-oss-date",
     "expires": "x-oss-expires", "signed_headers": "x-oss-signed-headers", "signature": "x-oss-signature"},
    additional_headers_line=True, unsigned_payload_only=True,
)


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote(value: str, *, safe: str = "/") -> str:
    """RFC 3986 转义。**`~` 不能被转义** —— 这是 SigV4 和 urllib 默认行为不一样的地方,
    也是签名对不上时最难查的一处:服务端按自己的规则重算,差一个字符就是 403。"""
    return urllib.parse.quote(value, safe=safe + "~")


def signing_key(secret: str, date: str, region: str, flavor: Flavor) -> bytes:
    """派生签名密钥。**四步一步都不能少**,而且第一步各家不同(见 Flavor.prefix)。"""
    key = _hmac((flavor.prefix + secret).encode("utf-8"), date)
    key = _hmac(key, region)
    key = _hmac(key, flavor.service)
    return _hmac(key, flavor.terminator)


def canonical_request(
    method: str, path: str, query: str, headers: dict[str, str], payload_hash: str,
    flavor: "Flavor | None" = None,
) -> tuple[str, str]:
    """规范化请求 + 签名头清单。头名小写、按 ASCII 排序、值去掉首尾空格。"""
    items = sorted((name.lower(), str(value).strip()) for name, value in headers.items())
    signed = ";".join(name for name, _ in items)
    lines = [method, path, query, "".join(f"{name}:{value}\n" for name, value in items)]
    if flavor is not None and flavor.additional_headers_line:
        lines.append("")  # AdditionalHeaders:阿里云要这一行,哪怕是空的
    else:
        lines.append(signed)
    lines.append(payload_hash)
    return "\n".join(lines), signed


def authorization(
    *, method: str, path: str, query: str, headers: dict[str, str], payload_hash: str,
    access_key: str, secret: str, region: str, stamp: str, flavor: Flavor,
) -> str:
    """`Authorization` 头的值。"""
    date = stamp[:8]
    canonical, signed = canonical_request(method, path, query, headers, payload_hash, flavor)
    scope = f"{date}/{region}/{flavor.service}/{flavor.terminator}"
    to_sign = "\n".join([flavor.algorithm, stamp, scope, sha256_hex(canonical.encode("utf-8"))])
    signature = hmac.new(signing_key(secret, date, region, flavor), to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return (f"{flavor.algorithm} Credential={access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}")


def presigned_query(
    *, method: str, path: str, host: str, expires: int,
    access_key: str, secret: str, region: str, stamp: str, flavor: Flavor,
) -> str:
    """一条**限时**的直链的查询串。

    签名进查询串而不是头里,所以任何 HTTP 客户端(以及供应商的服务器)都取得到它 ——
    这正是"本地文件怎么变成一条公网直链"的答案:不必把桶设成公共读。
    """
    date = stamp[:8]
    scope = f"{date}/{region}/{flavor.service}/{flavor.terminator}"
    names = flavor.query_names
    params = {
        names["algorithm"]: flavor.algorithm,
        names["credential"]: f"{access_key}/{scope}",
        names["date"]: stamp,
        names["expires"]: str(expires),
        names["signed_headers"]: "host",
    }
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))
    canonical, _ = canonical_request(method, path, query, {"host": host}, UNSIGNED, flavor)
    to_sign = "\n".join([flavor.algorithm, stamp, scope, sha256_hex(canonical.encode("utf-8"))])
    signature = hmac.new(signing_key(secret, date, region, flavor), to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return f"{query}&{names['signature']}={signature}"
