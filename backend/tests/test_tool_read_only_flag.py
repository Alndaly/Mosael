"""`read_only` 说的是「这个工具改不改得动东西」,不是「它有没有确认卡」。

这个标记有**两个消费者**,而它此前的定义只对得上其中一个:

  - 确认门控:`read_only = 不在 CONFIRMATION_TOOLS 里` —— 这是它的定义,自然对。
  - **子智能体的工具面**(sidecar 的 readOnlyTools):子智能体只拿只读工具,因为它的中间过程
    用户不看。这里的判据是"会不会改东西",而它借用了上面那个定义。

对大多数内置工具两者恰好一致,但浏览器动作不是:`browser_type` / `browser_click` /
`browser_upload` / `browser_evaluate` 都不走确认卡(入口 `browser_open` / `browser_pool_open`
走过一次),于是它们被算成只读、交给子智能体。而 `browser_pool_open` 开的会话用的是用户在别人
站点上的**真实登录身份** —— 一张入口卡之后,子智能体可以用那个身份填表、点提交、传文件、跑任意
JS,全程零张卡,而用户看不到子智能体的中间过程。

一个定义干两件事,其中一件是错的。这里把「改不改得动东西」写成**显式声明**。
"""

from __future__ import annotations

import mcp_server
from tests.util import fresh_client

#: 会改动东西的内置工具 —— 它们**都不该**被算成只读。走不走确认卡是另一个问题。
MUTATING = {
    # 浏览器里的每一个动作都作用在真实页面上;开池会话时那还是用户的登录身份。
    "browser_type",
    "browser_click",
    "browser_upload",
    "browser_evaluate",
    "browser_navigate",
    "browser_scroll",
    "browser_close",
    # 后面这些写的是本应用的数据,不至于伤及外部,但同样不是"只读"。
    "create_project",
    "remember",
    "forget",
    "update_asset",
    "update_asset_tags",
    "notify_workspace",
    "transcribe_asset",
    "update_plan",
    "invoke_plugin_tool",
}


def _specs(client) -> dict[str, dict]:
    return {spec["name"]: spec for spec in client.get("/api/agent/tools").json()}


def test_mutating_tools_are_not_advertised_as_read_only() -> None:
    client = fresh_client()
    specs = _specs(client)
    wrong = [name for name in MUTATING if name in specs and specs[name]["read_only"]]
    assert wrong == [], f"这些工具会改东西,却被标成只读(于是子智能体拿得到):{sorted(wrong)}"


def test_browser_actions_stay_out_of_a_subagents_hands() -> None:
    """点名浏览器那一组 —— 它是唯一能拿用户真实身份去做事的一组。"""
    client = fresh_client()
    specs = _specs(client)
    for name in ("browser_type", "browser_click", "browser_upload", "browser_evaluate"):
        assert specs[name]["read_only"] is False, f"{name} 被标成只读"


def test_genuinely_read_only_tools_stay_available() -> None:
    """别把子智能体废掉:它存在的意义就是替主智能体去翻素材、读文档、查网页。"""
    client = fresh_client()
    specs = _specs(client)
    for name in ("list_assets", "web_search", "fetch_url", "browser_read"):
        assert specs[name]["read_only"] is True, f"{name} 是只读的,不该被挡在子智能体外面"


def test_every_builtin_tool_declares_it() -> None:
    """新增工具时必须表态。**默认落在"会改东西"那边** —— 漏掉的那个恰恰是没人想过后果的那个。"""
    client = fresh_client()
    builtin = {name for name in _specs(client) if not name.startswith("plugin__")}
    declared = mcp_server.READ_ONLY_TOOLS | set(mcp_server.CONFIRMATION_TOOLS) | mcp_server.MUTATING_TOOLS
    missing = builtin - declared
    assert missing == set(), f"这些工具没有声明会不会改东西:{sorted(missing)}"


def test_confirmation_tools_are_never_read_only() -> None:
    """走确认卡就说明它会改东西 —— 两套声明不能互相打架。"""
    assert not (mcp_server.READ_ONLY_TOOLS & set(mcp_server.CONFIRMATION_TOOLS))
