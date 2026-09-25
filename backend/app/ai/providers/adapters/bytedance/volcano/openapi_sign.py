"""火山引擎 OpenAPI 的 AK/SK 请求签名(HMAC-SHA256)。

文档:https://www.volcengine.com/docs/6369/67269。和 AWS SigV4 同一个套路,但**不是**它:
没有 "AWS4" 前缀,凭据范围以 `/request` 结尾,派生链是 日期 → 地域 → 服务 → "request"。

住在 ai 层而不是 integrations:同一个签名有两个使用者 —— 拉账号可用音色(integrations/volc_openapi,
服务 `speech_saas_prod`)和音乐生成(adapters/bytedance/volcano/music,服务 `imagination`)。下层不能
认识上层(tests/test_import_layering),所以它放在两者都够得着的这一层,服务名由调用方给。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac

HOST = "open.volcengineapi.com"
REGION = "cn-beijing"


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signed_headers(
    ak: str,
    sk: str,
    query: str,
    body: bytes,
    *,
    service: str,
    region: str = REGION,
    host: str = HOST,
    now: dt.datetime | None = None,
) -> dict[str, str]:
    """一次 POST 的全部请求头(含 Authorization)。

    派生链(日期 → 地域 → 服务 → request)意味着签名密钥永远不等于 SK 本身,一张泄露的签名
    不会泄露凭据。`now` 只给测试用(签名随时间变)。
    """
    moment = now or dt.datetime.now(dt.UTC)
    x_date = moment.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest()

    signed_header_names = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            query,
            f"host:{host}",
            f"x-content-sha256:{payload_hash}",
            f"x-date:{x_date}",
            "",
            signed_header_names,
            payload_hash,
        ]
    )
    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        ["HMAC-SHA256", x_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
    )

    signing_key = _sign(_sign(_sign(sk.encode("utf-8"), short_date), region), service)
    signing_key = _sign(signing_key, "request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Host": host,
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": (
            f"HMAC-SHA256 Credential={ak}/{scope}, "
            f"SignedHeaders={signed_header_names}, Signature={signature}"
        ),
    }
