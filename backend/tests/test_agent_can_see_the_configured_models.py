"""智能体要能查到「这台机器上配了哪些供应商和模型」。

在这之前它查不到。工具表里唯一沾边的是 `list_generation_models`,而它只认 image / video;
对话模型、TTS、连接列表、各能力的默认,一个都拿不到,系统提示词里也没有。

后果不是"少个功能"。工作流 `llm` 节点的 config 要的是 `profile_id`(不透明 id)+ `model`
两个值,而模型两个都查不到 —— 于是用户说「把这个工作流的模型换成某某」时,它只能 `ask_user`,
或者按供应商名字猜一个字符串填进去,跑起来才失败。真实对话里两种都发生过。

这条测试钉的是工具的**契约**,不是它存在:

- 一次调用同时给出连接 id 和模型名(缺一不可,id 推不出来);
- 用户自己设过的默认能认出来,没设过的不替他编一个;
- 执行面会转发下去。这一条是实测出来的,不是照着直觉写的:`automation`(工作流 / 画板走的
  那条)= `direct` + `gateway`,所以 **OAuth 订阅在工作流里是可用的** —— 第一版工具描述把
  这一点写反了,是这条测试当场抓出来的。真正进不了 `automation` 的是**填了 API Key 却没填
  base_url** 的连接:两条子通道都收不下它,而它在 `agent` 上答得好好的。
"""

from __future__ import annotations

import mcp_server
from app.core.db import SessionLocal
from tests.util import add_provider, fresh_client

from tests.test_mcp_tool_payloads import _route_through


def _setup(client) -> None:
    with SessionLocal() as db:
        add_provider(
            db,
            name="自建端点",
            vendor="openai-compatible",
            base_url="http://127.0.0.1:1/v1",
            api_key="k",
            auth_type="api_key",
            enabled=True,
            model="qwen-max",
            capability_ids=["chat"],
            make_default=True,
        )
        # 订阅制:后端直连用不了它(没有 base_url / api_key),但 sidecar 的 gateway 通道可以,
        # 而 automation 含 gateway —— 所以它在工作流里是可用的。
        add_provider(
            db,
            name="订阅",
            vendor="anthropic",
            base_url="",
            api_key="",
            auth_type="oauth",
            oauth_credential={"type": "oauth", "access": "tok", "refresh": "r", "expires": 4102444800000},
            enabled=True,
            model="claude-sonnet",
            capability_ids=["chat"],
            make_default=False,
        )
        # 没填地址的 API Key 连接:direct 要 base_url、gateway 只收 OAuth,两边都落空。
        add_provider(
            db,
            name="没填地址",
            vendor="openai",
            base_url="",
            api_key="k",
            auth_type="api_key",
            enabled=True,
            model="半配好的模型",
            capability_ids=["chat"],
            make_default=False,
        )
        db.commit()


def test_一次调用同时给出连接id和模型名(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    _setup(client)
    _route_through(monkeypatch, client)

    reply = mcp_server.list_provider_models(capability="chat")
    chat = {item["model"]: item for item in reply["models"]}
    assert "qwen-max" in chat, reply

    entry = chat["qwen-max"]
    # 两半都要有:`model` 单独填进 llm 节点是不够的,而 profile_id 从供应商名字推不出来。
    assert entry["profile_id"], entry
    assert entry["provider"] == "自建端点"
    assert entry["capability"] == "chat"


def test_认得出用户自己设过的默认(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    _setup(client)
    _route_through(monkeypatch, client)

    models = mcp_server.list_provider_models(capability="chat")["models"]
    assert [item["model"] for item in models if item["is_default"]] == ["qwen-max"]
    # 没设过默认的能力就是没设过 —— 不替他从候选里挑一个充数。
    assert all(not item["is_default"] for item in mcp_server.list_provider_models(capability="tts")["models"])


def test_执行面会转发下去(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    _setup(client)
    _route_through(monkeypatch, client)

    def names(surface: str) -> set[str]:
        return {item["model"] for item in mcp_server.list_provider_models(capability="chat", surface=surface)["models"]}

    # automation = direct + gateway,运行时按鉴权方式分派 —— API Key 和 OAuth 都在里面。
    assert names("automation") == {"qwen-max", "claude-sonnet"}
    assert names("direct") == {"qwen-max"}
    assert names("gateway") == {"claude-sonnet"}
    # 真正的坑:没填地址的那条两个子通道都进不去,却在 agent 上答得好好的。
    assert "半配好的模型" not in names("automation")
    assert "半配好的模型" in names("agent")


def test_填错的取值当场说清楚而不是换回一个422(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    _setup(client)
    _route_through(monkeypatch, client)

    # 模型看到 422 不会说「我填错了参数」,它会换个词再试一次。所以合法取值要写在错误里。
    for bad, kwargs in (("surface", {"surface": "gateway-ish"}), ("capability", {"capability": "chat-ish"})):
        try:
            mcp_server.list_provider_models(**kwargs)
        except ValueError as error:
            assert bad in str(error) or "valid" in str(error) or "has" in str(error), error
        else:  # pragma: no cover - 只在契约破了时走到
            raise AssertionError(f"{bad} 填错了却没报错")


def test_回包里带着这次问的执行面(monkeypatch) -> None:
    """空列表有两种含义:什么都没配,和这条通道上没有。分不开的话模型只会报错一次。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    _setup(client)
    _route_through(monkeypatch, client)

    assert mcp_server.list_provider_models()["surface"] == "all"
    assert mcp_server.list_provider_models(surface="automation")["surface"] == "automation"


def test_它作为只读工具送达各运行时() -> None:
    """工具定义在 mcp_server,但各 runtime(sidecar / MCP 客户端 / 飞书)读的是 manifest。

    两个标都要对:`confirmation` 为真会让每次查询都弹一张卡(查一下配了什么不该要人批准),
    `read_only` 为假则子智能体拿不到它 —— 而"替我查一下现在用的什么模型"正是该派子智能体的活。
    """
    from app.db.models import User
    from app.domain.agent import tool_manifest

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        user_id = db.query(User).first().id
        spec = next(s for s in tool_manifest.agent_tool_specs(db, user_id) if s.name == "list_provider_models")
    assert spec.confirmation is False
    assert spec.read_only is True


def test_描述里名出全部合法能力() -> None:
    """参数的合法取值要写在**模型看得到的地方**,不能只在回包里。

    真机上撞过:模型要查 LLM,写了 `capability="text"` —— 这套词汇里它叫 `chat`,而当时描述只写
    「filters to one of the returned capabilities」,那份清单要等回包才看得到。于是白跑一轮,
    用户的轨迹里留下一个红色的「失败」,而工具本身是好的。

    `surface` 当时把四个取值都写进了描述,`capability` 没有 —— 这条测试钉的就是这个不对称,
    并且防止后端加一种能力之后描述开始说谎(那正是被它自己的枚举挡下来的那类错误)。
    """
    import asyncio

    from app.domain.provider_defaults import DEFAULTABLE_CAPABILITIES

    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    description = tools["list_provider_models"].description or ""
    missing = [one for one in DEFAULTABLE_CAPABILITIES if one not in description]
    assert not missing, f"这些能力没有写进工具描述,模型只能靠猜:{missing}"
