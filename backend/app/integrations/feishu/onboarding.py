"""扫码一键创建机器人(OAuth device authorization grant,移植自前身项目):用户扫码授权,飞书替他建好
自建应用、配好权限和事件订阅,我们轮询拿到 app_id / app_secret 就存成一个机器人并连上。

## 建完就把**发起人**绑上这台机器人

官方《一键创建应用》(https://open.feishu.cn/document/mcp_open_tools/integrating-agents-with-feishu/create-an-app-in-one-click-java)
的注册回包里带着**扫码那个人**的 `user_info` —— 我们在 `begin` 那一步用 `request_user_info=open_id`
点名要它。此前只从里面读 `tenant_brand`(判 feishu / lark),`open_id` 直接丢了:于是机器人建出来
谁都不认识,而"创建完自动绑定了"只是设置页列了**整个工作区**的绑定造成的错觉(键那一维见
domain/feishu/bindings)。

所以 `begin` 那一步要记下**是谁发起的**(路由里有 `CurrentUser`),建完机器人之后把
(新机器人, 那个 open_id, 发起人)写成一条绑定 —— 走 `bindings.bind_member`,和成员自己兑码那条路
**同一处**写绑定,键永远是 `(workspace_id, bot_id, open_id)`。发起人已经不是这个工作区的成员
(或被删了)就不写,记一条日志:**不报错**,机器人已经建好了。

⚠️ **`user_info.open_id` 的「应用归属」官方没写** —— 那个 id 是"新建应用里的那个人",还是注册平台
视角的那个人,文档没说。所以这里**不猜**:照实写。归属要是不对,这个人第一条消息就会
`resolve_sender(bot, open_id)` 认不出,而第一半那两句回复说得清是哪台机器人、指得回面板生成新码
—— 那是**可见的**,不是静默的。**不做任何"看起来一定成功"的猜测性回填。**

## 轮询按官方的来(两处此前不对)

- **`slow_down` 带回的新间隔要用上**:官方 Python SDK 是 `interval += 5`,服务端也可以直接在回包里
  给一个新的 `interval` —— 两种都认。此前这个值被完全忽略(`interval` 只在 begin 读一次),
  于是越问越快的请求被越来越多地判成 `slow_down`,而这个错误码本身就在提醒你慢下来。
- **有效期两种拼写都认**:服务端实际发的是 `expires_in`(官方 Python SDK 读的也是它,3600),
  `expire_in` 只是 Go SDK 那一侧的拼写变体。此前只认后者 → 永远落回 600 秒,用户还在确认页上就被
  报「扫码超时」,而那个二维码其实还有五十分钟。
- **`domain_switched` 双向、立刻再问**:扫码的人原来在另一个域(feishu ⇄ lark)时,换到他的域上
  **马上**再问一次(不在旧域上白等一轮),一次扫描只换一次 —— 官方的 `_handle_poll_response` 就是
  这个形状。此前只在 poll 里单向判一次,从 lark 开始扫 feishu 的人换不回去。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.core.db import SessionLocal
from app.core.http_retry import RetryingClient
from app.domain.feishu import bindings, bots
from app.integrations.feishu import client, connections

logger = logging.getLogger(__name__)

ONBOARD_ACCOUNTS_URLS = {"feishu": "https://accounts.feishu.cn", "lark": "https://accounts.larksuite.com"}
ONBOARD_REGISTRATION_PATH = "/oauth/v1/app/registration"

#: 品牌 → 我们这边的域名名。官方 SDK 判的是 `user_info.tenant_brand`(这次扫码的人在哪个域),
#: 和 `ONBOARD_ACCOUNTS_URLS` 的键一一对应 —— 两向都成立:从 lark 开始、扫的是 feishu 的人也要换回去。
_DOMAIN_BY_BRAND = {"feishu": "feishu", "lark": "lark"}

#: begin 没给间隔 / 有效期时的兜底(秒)。官方 Python SDK 就是这两个数。
_DEFAULT_INTERVAL_SECONDS = 5.0
_DEFAULT_EXPIRE_SECONDS = 600.0
#: `slow_down` 而服务端没给新间隔时加多少 —— 官方 Python SDK 那一句 `interval += 5`。
_SLOW_DOWN_STEP_SECONDS = 5.0

_onboard_lock = threading.Lock()
#: workspace_id -> {phase, qr_url, user_code, error, app_id, _gen, _user_id}
#: 下划线那两栏是内部的(这一轮的代号、这次扫码是谁发起的),不出现在 status 出口里。
_onboard_state: dict[str, dict[str, Any]] = {}


def _post_registration(base_url: str, body: dict[str, str]) -> dict[str, Any]:
    with RetryingClient(timeout=10.0, max_retries=0) as client:
        response = client.post(f"{base_url}{ONBOARD_REGISTRATION_PATH}", data=body)
    try:
        return response.json()
    except ValueError:
        return {}


def _seconds(value: Any, fallback: float) -> float:
    """回包里那个"多少秒"的字段。认不出、不是正数就用兜底 —— 别的都好说,**死线不能是 0**。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    return seconds if seconds > 0 else fallback


def _expire_seconds(res: dict[str, Any]) -> float:
    """这次扫码多久过期。**两种拼写都认**(见模块说明:`expires_in` 是服务端/官方 Python SDK 的写法,
    `expire_in` 是 Go SDK 那个变体)。"""
    for key in ("expires_in", "expire_in"):
        if res.get(key) is not None:
            return _seconds(res.get(key), _DEFAULT_EXPIRE_SECONDS)
    return _DEFAULT_EXPIRE_SECONDS


def _poll_interval(res: dict[str, Any], current: float) -> float:
    """`slow_down` 之后下一次隔多久:服务端给了新 `interval` 就用它,没给就按官方 +5 秒。"""
    return _seconds(res.get("interval"), 0.0) or (current + _SLOW_DOWN_STEP_SECONDS)


def _public(state: dict[str, Any]) -> dict[str, Any]:
    """出口那一份:内部两栏(`_gen`、`_user_id`)不出去。"""
    return {key: value for key, value in state.items() if not key.startswith("_")}


def _log_binding(workspace_id: str, bot_id: str, open_id: str, user_id: str, bound: bool) -> None:
    """自动绑定成没成,写清楚是哪一种 —— 它是"建完就绑好了"这件事唯一的痕迹(不报错,只记)。"""
    if bound:
        logger.info("feishu onboarding: bot=%s 建好并绑定了发起人 user=%s(ws=%s)", bot_id, user_id, workspace_id)
    elif not open_id:
        logger.info("feishu onboarding: 注册回包里没有 user_info.open_id,bot=%s 没有自动绑定(ws=%s)",
                    bot_id, workspace_id)
    elif not user_id:
        logger.info("feishu onboarding: 这次扫码没有记下发起人,bot=%s 没有自动绑定(ws=%s)", bot_id, workspace_id)
    else:
        logger.info("feishu onboarding: 发起人 user=%s 已不在工作区 %s 里,bot=%s 没有自动绑定",
                    user_id, workspace_id, bot_id)


def begin_onboarding(workspace_id: str, user_id: str, domain: str = "feishu") -> dict[str, Any]:
    """发起一次扫码创建。`user_id` 是**发起这次扫码的成员** —— 建完机器人要绑的就是他/她。"""
    base_url = ONBOARD_ACCOUNTS_URLS.get(domain, ONBOARD_ACCOUNTS_URLS["feishu"])
    init_res = _post_registration(base_url, {"action": "init"})
    if "client_secret" not in (init_res.get("supported_auth_methods") or []):
        raise client.FeishuError("feishuErr_qrUnsupported")
    res = _post_registration(
        base_url,
        {"action": "begin", "archetype": "PersonalAgent", "auth_method": "client_secret", "request_user_info": "open_id"},
    )
    device_code = res.get("device_code")
    if not device_code:
        raise client.FeishuError("feishuErr_noDeviceCode")
    state = {
        "phase": "waiting_scan",
        "qr_url": res.get("verification_uri_complete") or "",
        "user_code": res.get("user_code") or "",
        "error": None,
        "app_id": None,
        #: 建完机器人要绑的是**这个人**(见模块说明)。轮询那条线程也拿到它一份(当参数传),
        #: 这样"该绑谁"不依赖共享状态的读写先后。
        "_user_id": user_id,
    }
    with _onboard_lock:
        gen = int((_onboard_state.get(workspace_id) or {}).get("_gen") or 0) + 1
        _onboard_state[workspace_id] = {**state, "_gen": gen}
    threading.Thread(
        target=_poll_onboarding,
        args=(
            workspace_id,
            device_code,
            domain,
            _seconds(res.get("interval"), _DEFAULT_INTERVAL_SECONDS),
            _expire_seconds(res),
            gen,
            user_id,
        ),
        daemon=True,
    ).start()
    return _public(state)


def _poll_onboarding(
    workspace_id: str, device_code: str, domain: str, interval: float, expire_in: float, gen: int, user_id: str
) -> None:
    deadline = time.time() + expire_in
    current_domain = domain
    switched = False
    while time.time() < deadline:
        with _onboard_lock:
            if int((_onboard_state.get(workspace_id) or {}).get("_gen") or 0) != gen:
                return  # superseded by a newer scan
        base_url = ONBOARD_ACCOUNTS_URLS.get(current_domain, ONBOARD_ACCOUNTS_URLS["feishu"])
        try:
            res = _post_registration(base_url, {"action": "poll", "device_code": device_code, "tp": "ob_app"})
        except Exception:
            time.sleep(interval)
            continue
        #: 扫码的人原来在另一个域:换到他的域上、**立刻**再问一次(官方 SDK 同款:这一轮不问、也不等
        #: 一个 interval)。一次扫描只换一次 —— 换回来再换回去就是在两个域之间弹。
        target = _DOMAIN_BY_BRAND.get(str((res.get("user_info") or {}).get("tenant_brand") or "").strip().lower())
        if target and target != current_domain and not switched:
            current_domain = target
            switched = True
            continue
        app_id, app_secret = res.get("client_id"), res.get("client_secret")
        if app_id and app_secret:
            open_id = str((res.get("user_info") or {}).get("open_id") or "").strip()
            with SessionLocal() as db:
                #: 机器人和它的第一条绑定**一个事务**:建好了却没有那条绑定,正是这次要修掉的样子。
                bot = bots.create_bot(db, workspace_id=workspace_id, app_id=str(app_id), app_secret=str(app_secret))
                bound = bindings.bind_member(db, workspace_id, bot.id, open_id, user_id)
                db.commit()
                bot_id = bot.id
            _log_binding(workspace_id, bot_id, open_id, user_id, bound)
            with _onboard_lock:
                _onboard_state[workspace_id] = {"phase": "done", "qr_url": None, "user_code": None, "error": None,
                                                "app_id": app_id, "_gen": gen}
            try:
                connections.start_connection(bot_id)
            except Exception:
                logger.exception("feishu onboarding saved bot but connection failed ws=%s", workspace_id)
            return
        error = res.get("error") or ""
        if error in {"access_denied", "expired_token"}:
            with _onboard_lock:
                _onboard_state[workspace_id] = {"phase": "error", "qr_url": None, "user_code": None, "app_id": None,
                                                "error": "用户拒绝了授权" if error == "access_denied" else "二维码已过期",
                                                "_gen": gen}
            return
        if error == "slow_down":
            #: 服务端说"你问得太快了":用新的间隔 —— **下一次**轮询就按它来。
            interval = _poll_interval(res, interval)
        time.sleep(interval)
    with _onboard_lock:
        _onboard_state[workspace_id] = {"phase": "error", "qr_url": None, "user_code": None, "app_id": None,
                                        "error": "扫码超时,请重试。", "_gen": gen}


def onboarding_status(workspace_id: str) -> dict[str, Any]:
    with _onboard_lock:
        state = dict(_onboard_state.get(workspace_id) or {"phase": "idle"})
    return _public(state)
