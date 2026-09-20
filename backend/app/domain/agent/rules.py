from __future__ import annotations

from dataclasses import dataclass
from typing import Any

"""放行准则:auto 档下,`external` 那一类调用要不要问人。

几类撤不回来的操作,**同一种判据**,各有三档:

    ask    (默认) 一律弹卡问人,判断者不参与
    judge  交给那个与对话隔离的判断者,由它决定放行还是问人
    always 不问,也不过判断者,直接放行

`always` 比 `judge` 宽:judge 至少还有一次独立判断,而它等于把这一整类操作交出去。之所以提供,
是因为没有它的人会去把整个会话切成 bypass —— 那连另外两类也一起放开了。**给一个精确的开关,
好过逼人用一个粗的。**

曾经有过两份白名单(允许的请求主机、允许的发布账号),它们是这两类唯一能自动放行的路:名单命中
直接 ALLOW、连判断者都不过,不命中直接 DENY、判断者也不参与。删掉的理由是它们**没在工作**:
那份清单既难写(精确匹配、不支持通配)又难维护(换个 CDN 域名就失效),于是绝大多数人的名单
永远是空的 —— 也就是说「自动放行」这一档对这两类从来没生效过,只是每次都多问一遍。而界面上
那句"名单之外的情况会交给判断者"只对 run_code 成立,对这两项是错的。

删掉之后是**收紧**而不是放开:此前名单命中是确定性放行,现在最宽也要过判断者那一关。

准则是**工作区级**的。自由文本(notes)只作为判断者的补充依据,**不能单独放行任何东西**。
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


def gates() -> dict[str, str]:
    """有哪些档、各自叫什么 —— **从确认卡注册表推导**。

    此前这里手写着一串档位键和三份理由文案,于是每接一个新能力都要在权限领域里改四处 ——
    而它不该认识任何一个具体的第三方软件叫什么。现在每张确认卡自己声明 `gate` 和
    `gate_label`(见 confirmable/registry),这里只负责把它们收起来。
    """
    from app.domain.agent import confirmable

    found = {tool.gate: tool.gate_label for tool in confirmable.tool_specs().values() if tool.gate}
    return dict(sorted(found.items()))


#: 认得的档位。**存进来的任何别的值都读成 ask** —— 一个不认识的字符串必须落到最保守的那一档,
#: 而不是落到"最后一个 elif"碰巧是什么。前后空格、大小写不同的写法都算不认识:配置里的
#: "ALWAYS " 不该悄悄等于"完全放行"。
LEVELS = ("ask", "judge", "always")


def default_rules() -> dict[str, Any]:
    """没配过的工作区就是这一份:每一类都问人,判断者一次都不调。"""
    return {key: "ask" for key in gates()} | {"notes": ""}


def normalize(raw: Any) -> dict[str, Any]:
    """把用户存进来的东西收敛成一种形状 —— 读取代码里因此不出现"万一是别的形状"的分支。

    老库里存过 `http_allow_hosts` / `publish_allow_accounts` 的行读出来是 `ask`:**不把名单
    翻译成 judge**,那是把"这几个主机可以"悄悄改成"任何主机都交给一次模型调用来定",比他配过的
    东西宽得多。删掉一个能力时继承它最保守的解释,再让用户自己决定要不要打开。
    """
    data = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in gates():
        level = str(data.get(key) or "ask")
        out[key] = level if level in LEVELS else "ask"
    out["notes"] = str(data.get("notes") or "")[:2000]
    return out


def _tool_gate() -> dict[str, str]:
    """工具名 → 它归哪一档。同样来自注册表。

    一个能力可以自成一档:沙箱里跑和不隔离地跑就是两档 —— 对「算个数」放开,不该连带放开
    「动我的文件」。谁和谁分开,由那几张卡自己说了算。
    """
    from app.domain.agent import confirmable

    return {name: tool.gate for name, tool in confirmable.tool_specs().items() if tool.gate}


def evaluate(tool: str, payload: dict[str, Any], rules: dict[str, Any]) -> Ruling:
    """这次调用在准则下是拒绝(弹卡),还是"规则没话说"(往下问判断者)。

    三种结论对应三个档位:`always` → ALLOW(判断者不参与)、`judge` → ASK(往下问它)、
    `ask` → DENY(弹卡)。
    """
    rules = normalize(rules)
    gate = _tool_gate().get(tool)
    if gate is None:
        # 其余 external(如 browser_pool_open、含外部节点的工作流)没有可枚举的判据 ——
        # 用户的登录身份、一整张图的后果,都不是一条准则能说清的。一律回到人。
        return Ruling(DENY, "这类操作没有可配置的放行判据")
    label = gates()[gate]
    level = rules[gate]
    if level == "always":
        return Ruling(ALLOW, f"{label}已设为完全放行")
    if level == "judge":
        return Ruling(ASK, f"{label}交给判断者")
    return Ruling(DENY, f"{label}默认要人确认")
