"""本地后端与 MosaelCloud 的契约:绑定(凭据只落本地)和社区分享的只读反代。

**为什么桌面端不直接调 Cloud**:设备码换到的那枚凭据是长期凭据。让渲染层拿着它,它就会进
localStorage / devtools / 任何一段页面脚本;而本地后端本来就有一个可以安全落盘的地方
(`EncryptedText`)。所以:

    渲染层 → 本地后端 /api/cloud/binding/* → MosaelCloud /device/*

渲染层只看得到 `status / email / device_id`,永远看不到 `token`。

云端不可达或被拒时,抛 `CloudUnavailable` / `CloudBindingError`;本地登录态与本地账号**完全不动**。

社区分享的**只读**反代(`api/routes/cloud.py` 的 `/cloud/v1/shares/*`)也走这里:它要的是"照
Cloud 的原样取回来",不是另起一套 HTTP 客户端 —— 云地址、`RetryingClient`、超时和异常映射只有
`_request_json` 这一份,`post_json` 和 `get_json` 都从它出。
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.core.http_retry import RetryingClient

from app.core.config import settings
from app.db.models import CloudBinding, User

#: 一次 Cloud 请求的等待上限(绑定和社区分享反代共用)。设备码换凭据是几毫秒的事,10 秒足够;
#: 再长只会让界面一直转圈 —— 反代这边超时会翻成 504,不把前端的请求一起拖住。
TIMEOUT_SECONDS = 10.0


class CloudBindingError(Exception):
    """Cloud 明确拒绝(或本部署没配 Cloud):带状态码、机器码和一句给人看的话。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CloudUnavailable(Exception):
    """连不上 Cloud。**不是**本地身份问题 —— 本地照常登录。"""


class CloudTimeout(CloudUnavailable):
    """连上了,但 Cloud 没在 `TIMEOUT_SECONDS` 内答完。

    **单独一种,因为经本地反代出去时它该说 504**:504 是"上游慢",503 是"到不了";两者对用户的
    处置差不多(等一等再试),但把慢说成到不了会让人去查网络。绑定那几条路由照旧按
    `CloudUnavailable` 接(→ 503),行为不变。
    """


def _request_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list]:
    """向 Cloud 发一次请求,把**远端原样的**状态码和 JSON 交回来。

    绑定和社区反代共用这一条:云地址、`RetryingClient`、超时、异常映射只写一遍 —— 两处各写一份,
    迟早一处改了云地址的来源、另一处没改。

    `payload is None` 走 GET,否则走带 JSON 体的 POST。远端不是 JSON(网关的 HTML 错误页)时回空
    dict,状态码仍然照原样交出去。
    """
    base = settings.cloud_url.strip().rstrip("/")
    if not base:
        raise CloudBindingError(
            503,
            "cloud_not_configured",
            "MosaelCloud is not configured for this deployment (MOSAEL_CLOUD_URL).",
        )
    try:
        # 后端往外发 HTTP 一律经 RetryingClient:出站检查装在它的传输层上(见 core/outbound_guard)。
        with RetryingClient(timeout=TIMEOUT_SECONDS, max_retries=0) as client:
            if payload is None:
                response = client.get(f"{base}{path}")
            else:
                response = client.post(f"{base}{path}", json=payload)
    except httpx.TimeoutException as exc:
        raise CloudTimeout(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise CloudUnavailable(str(exc)) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, (dict, list)) else {}


def post_json(path: str, payload: dict) -> tuple[int, dict]:
    """向 Cloud 发一次 JSON POST。测试会替换这个函数,不去碰网络。"""
    status, body = _request_json("POST", path, payload)
    return status, body if isinstance(body, dict) else {}


def get_json(path: str) -> tuple[int, dict | list]:
    """向 Cloud 发一次只读 GET。**和 `post_json` 共用云地址、客户端、超时和异常映射。**

    测试会替换这个函数,不去碰网络。返回值**不做业务解释**:状态码和回包原样交给调用方 ——
    社区分享的反代要的就是这个,它不替 Cloud 把 404 说成"分享不存在"(那是界面的事)。
    """
    return _request_json("GET", path)


def _failure(status: int, body: dict) -> CloudBindingError:
    code = str(body.get("error") or "cloud_error")
    messages = body.get("message")
    if isinstance(messages, dict):
        text = str(messages.get("en") or messages.get("zh") or "MosaelCloud rejected the request.")
    else:
        text = str(messages or "MosaelCloud rejected the request.")
    # 4xx 是"这次绑定不行"(设备码过期之类),原样交给界面;5xx 是 Cloud 的故障,对本地是 502。
    return CloudBindingError(status if 400 <= status < 500 else 502, code, text)


def start(user: User, device_name: str) -> dict:
    status, body = post_json("/device/code", {"device_name": device_name.strip()[:120]})
    if status != 200:
        raise _failure(status, body)
    try:
        return {
            "status": "pending_authorization",
            "device_code": str(body["device_code"]),
            "user_code": str(body["user_code"]),
            "verification_uri": str(body["verification_uri"]),
            "verification_uri_complete": str(body["verification_uri_complete"]),
            "expires_in": int(body["expires_in"]),
            "interval": int(body["interval"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudBindingError(502, "cloud_bad_response", "MosaelCloud returned an unexpected device code.") from exc


def complete(db: Session, user: User, device_code: str) -> dict:
    """用桌面端手里的 device_code 换凭据;未确认返回 pending,确认了就落库。"""
    if db.get(CloudBinding, user.id) is not None:
        raise CloudBindingError(409, "cloud_already_bound", "This local account is already bound to MosaelCloud.")

    status, body = post_json("/device/token", {"device_code": device_code})
    if status == 428:
        return {"status": "pending", "email": None, "device_id": None}
    if status != 200:
        raise _failure(status, body)

    credential = body.get("credential")
    if not isinstance(credential, dict):
        raise CloudBindingError(502, "cloud_bad_response", "MosaelCloud returned no credential.")
    account = credential.get("account")
    token = str(credential.get("token") or "")
    device_id = str(credential.get("device_id") or "")
    cloud_user_id = str((account or {}).get("id") or "") if isinstance(account, dict) else ""
    email = str((account or {}).get("email") or "") if isinstance(account, dict) else ""
    if not token or not device_id or not cloud_user_id:
        raise CloudBindingError(502, "cloud_bad_response", "MosaelCloud returned an incomplete credential.")

    db.add(
        CloudBinding(
            user_id=user.id,
            cloud_user_id=cloud_user_id,
            email=email,
            device_id=device_id,
            token=token,
        )
    )
    return {"status": "approved", "email": email, "device_id": device_id}


def configured() -> bool:
    """这个部署有没有接 MosaelCloud(看 `MOSAEL_CLOUD_URL`)。

    **必须和 `post_json` 里那条判断用同一份来源** ✓ —— 两处各算各的就会说出两句话 ✗。
    """
    return bool(settings.cloud_url.strip())


def status_of(db: Session, user: User) -> dict:
    # `configured` 是给界面首屏用的:没接的时候按钮该是灰的,而不是点了才报错。
    base = {"configured": configured()}
    row = db.get(CloudBinding, user.id)
    if row is None:
        return {**base, "bound": False, "email": None, "device_id": None, "created_at": None}
    return {
        **base,
        "bound": True,
        "email": row.email,
        "device_id": row.device_id,
        "created_at": row.created_at,
    }


def remove(db: Session, user: User) -> bool:
    """只删本地这一行。云端那台设备仍活着,撤销它的入口在官网的账号页。"""
    row = db.get(CloudBinding, user.id)
    if row is None:
        return False
    db.delete(row)
    return True
