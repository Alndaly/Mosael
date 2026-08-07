from __future__ import annotations

from dataclasses import dataclass
from typing import Any

"""放行准则:auto 档下,`external` 那一类调用要不要问人。

三类撤不回来的操作,**同一种判据**:

    ask   (默认) 一律弹卡问人,判断者不参与
    judge 交给那个与对话隔离的判断者,由它决定放行还是问人

规则本身**从不主动放行**。它只回答"这一类要不要往下问判断者" —— 最宽的结论也只是 ASK。

曾经有过两份白名单(允许的请求主机、允许的发布账号),它们是这两类唯一能自动放行的路:名单命中
直接 ALLOW、连判断者都不过,不命中直接 DENY、判断者也不参与。删掉的理由是它们**没在工作**:
那份清单既难写(精确匹配、不支持通配)又难维护(换个 CDN 域名就失效),于是绝大多数人的名单
永远是空的 —— 也就是说「自动放行」这一档对这两类从来没生效过,只是每次都多问一遍。而界面上
那句"名单之外的情况会交给判断者"只对 run_code 成立,对这两项是错的。

删掉之后是**收紧**而不是放开:此前名单命中是确定性放行,现在最宽也要过判断者那一关。

准则是**工作区级**的。自由文本(notes)只作为判断者的补充依据,**不能单独放行任何东西**。
"""

#: 三种结论。`ASK` 表示"规则没话说",由调用方决定要不要往下问判断者。
#: **`ALLOW` 现在没有任何产出它的路径** —— 唯一那条(白名单命中)删掉了。常量与 `Ruling.allowed`
#: 保留是因为调用方按它分支,而"规则可以确定性放行"这件事将来可能以别的形状回来;今天它恒为假。
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


#: 三类操作各自的档位键。顺序即界面顺序。
GATED = ("http_request", "publish", "run_code")

#: 认得的档位。**存进来的任何别的值都读成 ask** —— 一个不认识的字符串必须落到最保守的那一档,
#: 而不是落到"最后一个 elif"碰巧是什么。
LEVELS = ("ask", "judge")


def default_rules() -> dict[str, Any]:
    """没配过的工作区就是这一份:三类都问人,判断者一次都不调。"""
    return {key: "ask" for key in GATED} | {"notes": ""}


def normalize(raw: Any) -> dict[str, Any]:
    """把用户存进来的东西收敛成一种形状 —— 读取代码里因此不出现"万一是别的形状"的分支。

    老库里存过 `http_allow_hosts` / `publish_allow_accounts` 的行读出来是 `ask`:**不把名单
    翻译成 judge**,那是把"这几个主机可以"悄悄改成"任何主机都交给一次模型调用来定",比他配过的
    东西宽得多。删掉一个能力时继承它最保守的解释,再让用户自己决定要不要打开。
    """
    data = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in GATED:
        level = str(data.get(key) or "ask")
        out[key] = level if level in LEVELS else "ask"
    out["notes"] = str(data.get("notes") or "")[:2000]
    return out


#: 工具名 → 它归哪一档。
_TOOL_GATE = {"http_request": "http_request", "publish_asset": "publish", "run_code": "run_code"}

_ASK_REASON = {
    "http_request": "对外请求交给判断者",
    "publish": "公开发布交给判断者",
    "run_code": "本机执行代码交给判断者",
}
_DENY_REASON = {
    "http_request": "对外请求默认要人确认",
    "publish": "公开发布默认要人确认",
    "run_code": "本机执行代码默认要人确认",
}


def evaluate(tool: str, payload: dict[str, Any], rules: dict[str, Any]) -> Ruling:
    """这次调用在准则下是拒绝(弹卡),还是"规则没话说"(往下问判断者)。

    **没有 ALLOW 这一档了。** 规则最宽的结论是 ASK —— 确定性地放行的那条路(白名单)删掉了,
    所以任何一次自动放行都至少过了判断者那一关。
    """
    rules = normalize(rules)
    gate = _TOOL_GATE.get(tool)
    if gate is None:
        # 其余 external(如 browser_pool_open、含外部节点的工作流)没有可枚举的判据 ——
        # 用户的登录身份、一整张图的后果,都不是一条准则能说清的。一律回到人。
        return Ruling(DENY, "这类操作没有可配置的放行判据")
    if rules[gate] == "judge":
        return Ruling(ASK, _ASK_REASON[gate])
    return Ruling(DENY, _DENY_REASON[gate])
