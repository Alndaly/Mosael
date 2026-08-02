from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

"""放行准则:auto 档下,`external` 那一类调用的**确定性**判据。

判断者是非确定性的一环,所以它不能是唯一的闸 —— 它看到的参数正是那个可能已被网页内容影响的模型
写出来的。规则先判:

    明确拒绝 → 弹卡(判断者不参与,也翻不了案)
    明确允许 → 直接放行(确定性的答案不该花一次模型调用,也不该让一次模型调用有机会否掉它)
    没有覆盖 → 交给判断者

准则是**工作区级**的,结构化为主、自由文本为辅。结构化的部分可测、可解释、事后能复算;自由文本
只作为判断者的补充依据,**不能单独放行任何东西**。
"""

#: 三种结论。`ASK` 表示"规则没话说",由调用方决定要不要往下问判断者。
ALLOW = "allow"
DENY = "deny"
ASK = "ask"


@dataclass(frozen=True)
class Ruling:
    outcome: str
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOW

    @property
    def denied(self) -> bool:
        return self.outcome == DENY


def default_rules() -> dict[str, Any]:
    """没配过的工作区就是这一份:什么都不放行,run_code 连问都不问判断者。"""
    return {"http_allow_hosts": [], "publish_allow_accounts": [], "run_code": "ask", "notes": ""}


def normalize(raw: Any) -> dict[str, Any]:
    """把用户存进来的东西收敛成一种形状 —— 读取代码里因此不出现"万一是别的形状"的分支。"""
    data = raw if isinstance(raw, dict) else {}
    hosts = [str(item).strip().lower() for item in data.get("http_allow_hosts") or [] if str(item).strip()]
    accounts = [str(item).strip() for item in data.get("publish_allow_accounts") or [] if str(item).strip()]
    run_code = str(data.get("run_code") or "ask")
    return {
        "http_allow_hosts": hosts[:50],
        "publish_allow_accounts": accounts[:50],
        "run_code": run_code if run_code in ("ask", "judge") else "ask",
        "notes": str(data.get("notes") or "")[:2000],
    }


def evaluate(tool: str, payload: dict[str, Any], rules: dict[str, Any]) -> Ruling:
    """这次调用在准则下是允许、拒绝,还是没说。"""
    rules = normalize(rules)
    if tool == "http_request":
        return _http(payload, rules)
    if tool == "publish_asset":
        return _publish(payload, rules)
    if tool == "run_code":
        # 「这段 Python 安不安全」没有可结构化的判据。把它交给判断者去读一段代码,等于把闸门交给
        # 最不可测的一环 —— 默认不问,想开的人显式改成 judge。
        return Ruling(ASK if rules["run_code"] == "judge" else DENY, "run_code 默认要人确认")
    # 其余 external(如 browser_pool_open、含外部节点的工作流)没有可枚举的判据 ——
    # 用户的登录身份、一整张图的后果,都不是一条白名单能说清的。一律回到人。
    return Ruling(DENY, "这类操作没有可配置的放行判据")


def _http(payload: dict[str, Any], rules: dict[str, Any]) -> Ruling:
    host = (urlparse(str(payload.get("url") or "")).hostname or "").lower()
    if not host:
        return Ruling(DENY, "请求没有可识别的主机名")
    # 精确匹配,不做通配:`*.example.com` 这种写法里,哪些子域算数取决于谁在解析它 ——
    # 白名单要能被逐条读懂,而不是被逐条猜。
    if host in rules["http_allow_hosts"]:
        return Ruling(ALLOW, f"{host} 在允许的主机名单里")
    return Ruling(DENY, f"{host} 不在允许的主机名单里")


def _publish(payload: dict[str, Any], rules: dict[str, Any]) -> Ruling:
    account = str(payload.get("account_id") or "")
    # payload 里素材只是个 id —— 判断者对"要发出去的是什么"是瞎的,所以这一档的主判据只能是
    # "用哪个账号发"。名单外的账号不交给判断者,它没有能据以判断的东西。
    if account and account in rules["publish_allow_accounts"]:
        return Ruling(ALLOW, "发布账号在名单里")
    return Ruling(DENY, "发布账号不在名单里")
