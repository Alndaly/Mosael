"""AWS Signature V4 —— **纯标准库**。

插件进程里没有 boto3,也不该有:插件是按 stdio 协议跑的短命脚本,装一整个 SDK 只为签四个
请求,代价是安装体积、版本冲突,以及一条我们控制不了的供应链。SigV4 本身是一页纸的算法。

三家对象存储(S3 / 火山 TOS / 阿里云 OSS)的签名**同源但不同字**:算法名、日期头、
scope 的结尾、密钥派生链的第一步各不相同。所以这一份写成可参数化的,三家各是一个 `Flavor`
(用哪一个由 providers.py 那张表定)。

`Flavor` 同时就是 storage.Bucket 要的那个**签名方言**(sign / presign / list_v2)。
腾讯云 COS 的签名不是 SigV4 这一系,它的方言在 qsign.py。
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
    #: **阿里云 V4 与 AWS SigV4 的结构差异**(不只是换几个名字 —— 当初只换了名字,于是算法对、
    #: 格式错,真请求回的是 `400 Unknown parameter in Authorization header`):
    #:   · 只签默认那几类头:`x-oss-*`、`content-type`、`content-md5`(host 不签);
    #:   · 规范化请求里那一行是 `AdditionalHeaders`(我们不加附加头,所以是空行),不是 `SignedHeaders`;
    #:   · Authorization 里没有 `SignedHeaders`,逗号后不带空格;预签名串里也没有那个参数;
    #:   · 规范化 URI 带桶名:`/桶/对象`、列目录是 `/桶/` —— 虚拟主机式寻址也一样;
    #:   · 规范化查询串里**没有值的参数只写名字**(`uploads`,不是 `uploads=`)—— 分片上传的
    #:     `?uploads` 就是这种参数;按 SigV4 写成 `uploads=` 的话,算法对、串不对,还是 403。
    #: 核对来源是官方 SDK(alibabacloud-oss-v2 的 SignerV4),向量见 test_oss_signature_matches_the_sdk。
    aliyun_v4: bool = False
    #: 阿里云的 `x-oss-content-sha256` 目前**只收 `UNSIGNED-PAYLOAD`**(文档原话),
    #: 所以那一家不签正文哈希。
    unsigned_payload_only: bool = False

    #: 列目录用 list-objects-v2。三家都支持。
    list_v2 = True

    # —— storage.Bucket 用的方言接口 ——

    def sign(self, bucket, *, method: str, path: str, params: dict[str, str], headers: dict[str, str],
             body: bytes | None, now) -> dict[str, str]:
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        payload = UNSIGNED if body is None or self.unsigned_payload_only else sha256_hex(body)
        signed = {**headers, self.date_header: stamp, self.sha_header: payload}
        signed["authorization"] = authorization(
            method=method, path=quote(path), query=canonical_query(params, bare_empty=self.aliyun_v4),
            headers=signed,
            payload_hash=payload, access_key=bucket.access_key, secret=bucket.secret,
            region=bucket.region, stamp=stamp, flavor=self, bucket=bucket.bucket,
        )
        return signed

    def presign(self, bucket, *, method: str, path: str, expires: int, now) -> str:
        return presigned_query(
            method=method, path=quote(path), host=bucket.host, expires=expires,
            access_key=bucket.access_key, secret=bucket.secret, region=bucket.region,
            stamp=now.strftime("%Y%m%dT%H%M%SZ"), flavor=self, bucket=bucket.bucket,
        )


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
     "expires": "x-oss-expires", "signature": "x-oss-signature"},
    aliyun_v4=True, unsigned_payload_only=True,
)


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote(value: str, *, safe: str = "/") -> str:
    """RFC 3986 转义。**`~` 不能被转义** —— 这是 SigV4 和 urllib 默认行为不一样的地方,
    也是签名对不上时最难查的一处:服务端按自己的规则重算,差一个字符就是 403。"""
    return urllib.parse.quote(value, safe=safe + "~")


def canonical_query(params: dict[str, str], *, bare_empty: bool = False) -> str:
    """规范化查询串。`bare_empty`:没有值的参数只写名字(阿里云 V4 的写法,见 Flavor.aliyun_v4)。"""
    return "&".join(
        quote(k, safe="") if bare_empty and v == "" else f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(params.items())
    )


def signing_key(secret: str, date: str, region: str, flavor: Flavor) -> bytes:
    """派生签名密钥。**四步一步都不能少**,而且第一步各家不同(见 Flavor.prefix)。"""
    key = _hmac((flavor.prefix + secret).encode("utf-8"), date)
    key = _hmac(key, region)
    key = _hmac(key, flavor.service)
    return _hmac(key, flavor.terminator)


def _signs(flavor: "Flavor | None", name: str) -> bool:
    """这个头进不进签名。AWS 系全签;阿里云只签默认那几类(见 Flavor.aliyun_v4)。"""
    if flavor is None or not flavor.aliyun_v4:
        return True
    return name.startswith("x-oss-") or name in ("content-type", "content-md5")


def canonical_path(path: str, bucket: str, flavor: "Flavor | None") -> str:
    """规范化 URI。阿里云要带桶名(`/桶/对象`),另外两家就是请求路径本身。"""
    return f"/{bucket}{path}" if flavor is not None and flavor.aliyun_v4 else path


def canonical_request(
    method: str, path: str, query: str, headers: dict[str, str], payload_hash: str,
    flavor: "Flavor | None" = None,
) -> tuple[str, str]:
    """规范化请求 + 签名头清单。头名小写、按 ASCII 排序、值去掉首尾空格。"""
    items = sorted((name.lower(), str(value).strip()) for name, value in headers.items())
    items = [(name, value) for name, value in items if _signs(flavor, name)]
    signed = ";".join(name for name, _ in items)
    lines = [method, path, query, "".join(f"{name}:{value}\n" for name, value in items)]
    if flavor is not None and flavor.aliyun_v4:
        lines.append("")  # AdditionalHeaders:我们不加附加头,这一行是空的 —— 但必须占着
    else:
        lines.append(signed)
    lines.append(payload_hash)
    return "\n".join(lines), signed


def authorization(
    *, method: str, path: str, query: str, headers: dict[str, str], payload_hash: str,
    access_key: str, secret: str, region: str, stamp: str, flavor: Flavor, bucket: str = "",
) -> str:
    """`Authorization` 头的值。`bucket` 只有阿里云用得到(规范化 URI 里要它)。"""
    date = stamp[:8]
    canonical, signed = canonical_request(
        method, canonical_path(path, bucket, flavor), query, headers, payload_hash, flavor)
    scope = f"{date}/{region}/{flavor.service}/{flavor.terminator}"
    to_sign = "\n".join([flavor.algorithm, stamp, scope, sha256_hex(canonical.encode("utf-8"))])
    signature = hmac.new(signing_key(secret, date, region, flavor), to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    if flavor.aliyun_v4:
        return f"{flavor.algorithm} Credential={access_key}/{scope},Signature={signature}"
    return (f"{flavor.algorithm} Credential={access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}")


def presigned_query(
    *, method: str, path: str, host: str, expires: int,
    access_key: str, secret: str, region: str, stamp: str, flavor: Flavor, bucket: str = "",
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
    }
    if "signed_headers" in names:  # 阿里云没有这个参数(见 Flavor.aliyun_v4)
        params[names["signed_headers"]] = "host"
    query = canonical_query(params)
    canonical, _ = canonical_request(
        method, canonical_path(path, bucket, flavor), query, {"host": host}, UNSIGNED, flavor)
    to_sign = "\n".join([flavor.algorithm, stamp, scope, sha256_hex(canonical.encode("utf-8"))])
    signature = hmac.new(signing_key(secret, date, region, flavor), to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return f"{query}&{names['signature']}={signature}"
