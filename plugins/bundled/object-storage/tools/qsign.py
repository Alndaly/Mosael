"""腾讯云 COS 的请求签名(XML API 的 `q-sign-algorithm=sha1` 那一套)—— **纯标准库**。

它和另外三家不是一系:没有 SigV4 的 scope 与四步密钥派生,而是
「KeyTime → SignKey → HttpString → StringToSign → Signature」,全程 HMAC-SHA1。
几处和直觉不一样、错了只会回 403 的地方:

- 签的是**未转义的路径**(`/中文 文件.mp4`),不是 URL 里转义后的那串;
- 头和参数都是**键小写、值按 RFC 3986 转义**(`-_.~` 不转,`/` 要转),再按键排序;
- HttpString 每一段后面都有一个换行,**连最后一段也有**;
- StringToSign 里放的是 HttpString 的 **SHA1 十六进制**,不是它本身。

核对来源是官方 Python SDK(cos-python-sdk-v5 的 CosS3Auth),向量见
backend/tests/test_cos_signature_matches_the_sdk.py。

COS 也有一个 S3 兼容入口(SigV4),但它是兼容层;原生签名是官方 SDK 走的那条路,
对得上它的向量就对得上服务端。
"""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse

#: 进签名的头。和官方 SDK 的 filter_headers 同一份清单:其余的头(比如 user-agent)
#: 在路上可能被代理改掉,签进去反而会让签名失效。
_SIGNABLE = frozenset({
    "cache-control", "content-disposition", "content-encoding", "content-type", "content-md5",
    "content-length", "expect", "expires", "host", "if-match", "if-modified-since", "if-none-match",
    "if-unmodified-since", "origin", "range", "transfer-encoding",
})
#: 带着请求头签名时,签名本身的有效期。给得宽一点是为了容忍本机时钟的偏差;
#: 起点往前拨 60 秒也是同一个原因(和官方 SDK 一样)。
REQUEST_TTL = 900


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="-_.~")


def _signable(name: str) -> bool:
    name = name.lower()
    return name in _SIGNABLE or name.startswith("x-cos-")


def _pairs(items: dict[str, str]) -> list[tuple[str, str]]:
    return sorted((_quote(k).lower(), _quote(v)) for k, v in items.items())


def signature(*, method: str, path: str, params: dict[str, str], headers: dict[str, str],
              access_key: str, secret: str, start: int, end: int) -> dict[str, str]:
    """一次签名的全部字段(按 COS 的名字),顺序就是它们在串里的顺序。"""
    key_time = f"{start};{end}"
    header_pairs = _pairs({k: v for k, v in headers.items() if _signable(k)})
    param_pairs = _pairs(params)
    http_string = "\n".join([
        method.lower(), path,
        "&".join(f"{k}={v}" for k, v in param_pairs),
        "&".join(f"{k}={v}" for k, v in header_pairs),
    ]) + "\n"
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode('utf-8')).hexdigest()}\n"
    sign_key = hmac.new(secret.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    return {
        "q-sign-algorithm": "sha1",
        "q-ak": access_key,
        "q-sign-time": key_time,
        "q-key-time": key_time,
        "q-header-list": ";".join(k for k, _ in header_pairs),
        "q-url-param-list": ";".join(k for k, _ in param_pairs),
        "q-signature": hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"),
                                hashlib.sha1).hexdigest(),
    }


class Cos:
    """storage.Bucket 用的签名方言(接口见 storage.py 开头)。"""

    #: COS 只有 V1 的列目录(GET Bucket);`list-type=2` 不在它的参数表里。
    list_v2 = False

    def sign(self, bucket, *, method: str, path: str, params: dict[str, str], headers: dict[str, str],
             body: bytes | None, now) -> dict[str, str]:
        start = int(now.timestamp())
        fields = signature(method=method, path=path, params=params, headers=headers,
                           access_key=bucket.access_key, secret=bucket.secret,
                           start=start - 60, end=start + REQUEST_TTL)
        return {**headers, "authorization": "&".join(f"{k}={v}" for k, v in fields.items())}

    def presign(self, bucket, *, method: str, path: str, expires: int, now) -> str:
        """限时直链:签名字段整个放进查询串,只签 host —— 谁拿到链接都能用,过期作废。"""
        start = int(now.timestamp())
        fields = signature(method=method, path=path, params={}, headers={"host": bucket.host},
                           access_key=bucket.access_key, secret=bucket.secret,
                           start=start - 60, end=start + int(expires))
        return urllib.parse.urlencode(fields)


COS = Cos()
