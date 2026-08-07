"""三类撤不回来的操作,同一种判据:默认问你,想让判断者接管就显式打开。

**两个白名单删掉了。** 它们曾经是「对外请求」和「公开发布」唯一能自动放行的路 —— 名单命中放行,
不命中直接弹卡,判断者根本不参与。代价是这一屏要求用户先手抄一份主机名/账号 id 清单,而那份清单
既难写(精确匹配、不支持通配)又难维护(换个 CDN 域名就失效),于是绝大多数人的名单永远是空的 ——
也就是说「自动放行」这一档对这两类**从来没生效过**,只是每次都多问一遍。

页面上原本那句"名单之外的情况会交给判断者"也只对 run_code 成立,对这两项是错的:它们不命中是
DENY,不是 ASK。一句说明同时描述三项而只对一项为真,比没有说明更坏。

现在三项统一:`ask`(默认,一律问你)| `judge`(交给那个与对话隔离的判断者)。判断者仍然翻不了
任何东西 —— 它只能把"问你"变成"放行",不能把"拒绝"变成"放行"(见 domain/agent/rules.evaluate)。
"""

from __future__ import annotations

import pytest

from app.domain.agent import rules


def test_the_two_allowlists_are_gone() -> None:
    default = rules.default_rules()

    assert "http_allow_hosts" not in default
    assert "publish_allow_accounts" not in default


def test_three_categories_share_one_shape() -> None:
    """同一种判据同一种写法 —— 三项各自一套形状是上一版最难读的地方。"""
    default = rules.default_rules()

    assert default["http_request"] == "ask"
    assert default["publish"] == "ask"
    assert default["run_code"] == "ask"


@pytest.mark.parametrize(
    "tool,payload",
    [
        ("http_request", {"url": "https://api.example.com/x"}),
        ("publish_asset", {"account_id": "acc-1"}),
        ("run_code", {"code": "print(1)"}),
    ],
)
def test_the_default_is_still_to_ask(tool: str, payload: dict) -> None:
    """没配过的工作区什么都不自动放行 —— 删掉名单不等于放开。"""
    ruling = rules.evaluate(tool, payload, rules.default_rules())

    assert ruling.denied, ruling.reason


@pytest.mark.parametrize(
    "tool,payload,key",
    [
        ("http_request", {"url": "https://api.example.com/x"}, "http_request"),
        ("publish_asset", {"account_id": "acc-1"}, "publish"),
        ("run_code", {"code": "print(1)"}, "run_code"),
    ],
)
def test_turning_it_on_hands_the_call_to_the_judge(tool: str, payload: dict, key: str) -> None:
    """打开之后规则说"我没话说"(ASK),由判断者接着判 —— 而不是规则直接放行。

    **规则永远不主动放行**了:删掉名单也就删掉了唯一那条"确定性地允许"的路。这是收紧,不是放开
    —— 此前名单命中是 ALLOW,连判断者都不过。
    """
    ruling = rules.evaluate(tool, payload, {**rules.default_rules(), key: "judge"})

    assert ruling.outcome == rules.ASK, ruling.reason


def test_a_bad_value_falls_back_to_asking() -> None:
    """存进来一个不认识的档位,读出来必须是最保守的那个。"""
    normalized = rules.normalize({"http_request": "always", "publish": True, "run_code": "judge"})

    assert normalized["http_request"] == "ask"
    assert normalized["publish"] == "ask"
    assert normalized["run_code"] == "judge"


def test_everything_else_still_goes_back_to_a_human() -> None:
    """浏览器池、整张工作流图这些没有可枚举判据的,一律回到人 —— 这条没变。"""
    assert rules.evaluate("browser_pool_open", {"profile_id": "p"}, rules.default_rules()).denied


def test_old_rows_with_allowlists_read_as_ask() -> None:
    """老库里存过名单的行,读出来是"问你"。

    **不把名单翻译成 judge**:那是把"这几个主机可以"悄悄改成"任何主机都交给一次模型调用来定",
    比他配过的东西宽得多。删掉一个能力时,继承它的最保守解释,然后让用户自己决定要不要打开。
    """
    legacy = {"http_allow_hosts": ["api.example.com"], "publish_allow_accounts": ["acc-1"], "notes": "旧的"}

    normalized = rules.normalize(legacy)

    assert normalized["http_request"] == "ask"
    assert normalized["publish"] == "ask"
    assert normalized["notes"] == "旧的", "补充说明不该跟着一起丢"
