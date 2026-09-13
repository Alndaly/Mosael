"""上下文水位要说清**是什么占满的**,而不只给一个百分比。

「剩余 98%」这种单个数字回答不了任何该做的决定 —— 满了要清什么?清对话有用吗?而这个应用里
真正的大头往往**不是对话**:量出来每次请求的完整 prompt ≈ 12.3k,其中会话只有 6 条消息,
剩下的几乎全是**工具定义**(57 个工具的 JSON schema,每次请求重发一遍)。

只给百分比时,用户会去删对话 —— 删掉的那部分恰恰是最小的一块。

另外一处口径错:`cache_read` 的 token **也占着窗口**。它在计价上另算(便宜十倍),但在"还能装
多少"这个问题上和普通输入没有区别。此前只算 input+output,于是水位系统性偏乐观。
"""

from __future__ import annotations

from app.domain.context_meter import context_breakdown, context_tokens


def _assistant(text: str, **usage: int) -> dict:
    return {"role": "assistant", "content": text, "usage": usage}


def test_cache_reads_occupy_the_window_too() -> None:
    """计价上另算,占地方上一样占 —— 「还能聊多久」问的是后者。"""
    messages = [{"role": "user", "content": "hi"}, _assistant("ok", input=1000, output=200, cacheRead=8000)]
    assert context_tokens(messages) == 9200, "缓存读取没算进水位"


def test_a_turn_without_cache_is_unchanged() -> None:
    messages = [{"role": "user", "content": "hi"}, _assistant("ok", input=1000, output=200)]
    assert context_tokens(messages) == 1200


def test_the_breakdown_names_what_fills_the_window() -> None:
    """分项要能直接回答"该清什么"。"""
    messages = [{"role": "user", "content": "hi"}, _assistant("ok", input=1000, output=200, cacheRead=8000)]
    parts = context_breakdown(messages, system_prompt="系统提示" * 100, tool_tokens=9000, window=32000)

    names = {part["kind"] for part in parts["parts"]}
    assert {"tools", "system", "messages", "free"} <= names
    assert parts["window"] == 32000
    # 各分项加起来正好是窗口 —— 否则那条堆叠条读起来就是错的。
    assert sum(part["tokens"] for part in parts["parts"]) == 32000


def test_tools_are_reported_separately_because_they_are_the_big_one() -> None:
    """这个应用里工具定义常常比对话大一个量级 —— 把它并进"系统"会藏住真正的大头。"""
    parts = context_breakdown([], system_prompt="短", tool_tokens=9000, window=32000)
    by_kind = {part["kind"]: part["tokens"] for part in parts["parts"]}
    assert by_kind["tools"] == 9000


def test_free_space_never_goes_negative() -> None:
    """超出窗口时剩余是 0,不是负数 —— 负的进度条画不出来,也说明不了任何事。"""
    parts = context_breakdown([], system_prompt="", tool_tokens=50000, window=32000)
    by_kind = {part["kind"]: part["tokens"] for part in parts["parts"]}
    assert by_kind["free"] == 0


def test_default_chat_model_uses_its_resolved_profile_catalog_window(monkeypatch) -> None:
    """会话沿用默认模型时 profile_id 不写在会话上,但窗口仍应从那条默认连接的目录读取。"""
    from types import SimpleNamespace

    from app.domain.agent import host

    session = SimpleNamespace(
        provider_profile_id=None,
        model=None,
        owner_user_id="user-1",
        adapter_state=None,
        workspace_id="workspace-1",
        project_id=None,
        plan=None,
        analysis_video_mode="auto",
    )
    monkeypatch.setattr(
        host,
        "resolve_chat_provider",
        lambda *_args, **_kwargs: ({"context_window": None}, "k3", SimpleNamespace(id="profile-kimi")),
    )
    monkeypatch.setattr(
        host,
        "session_model_catalog",
        lambda _db, profile_id, user_id: (
            [{"id": "k3", "contextWindow": 1_048_576}]
            if (profile_id, user_id) == ("profile-kimi", "user-1")
            else []
        ),
    )
    monkeypatch.setattr(host, "build_system_prompt", lambda *_args: "")
    monkeypatch.setattr(host, "tool_definition_tokens", lambda *_args: 0)

    context = host.session_context(object(), session)

    assert context is not None
    assert context["window"] == 1_048_576
    assert context["used"] == 0


def test_对话不为空时_消息那一项就不能是零() -> None:
    """这条水位最核心的一件事:**聊得越多,条子越长**。

    此前它做不到。总量是供应商**量**的(锚点 usage),而 system/tools 是我们按 chars/3.5
    **估**的 —— JSON schema 那种密集文本会高估不少。估多了,`used - system - tools` 就是
    负数,再被 max(0, …) 夹成 0:「消息」恒为 0,占用条无论聊多久都停在同一个数字。
    在真实数据上量过:39 个会话里 27 个中招。
    """
    messages = [
        {"role": "user", "content": "问题" * 300},
        _assistant("回答" * 300, input=9000, output=400),
    ]
    # 固定开销估成 20000,而供应商量到的整条 prompt 才 9400 —— 典型的高估。
    parts = context_breakdown(messages, system_prompt="系统" * 500, tool_tokens=20000, window=32000)
    by_kind = {part["kind"]: part["tokens"] for part in parts["parts"]}
    assert by_kind["messages"] > 0, "聊了两轮,消息那一项却是 0"
    # 总量仍以供应商说的为准,而且分项之和正好等于它。
    assert parts["used"] == 9400
    assert by_kind["messages"] + by_kind["tools"] + by_kind["system"] == 9400
    # 工具仍然是大头 —— 这条水位要回答的正是"该清对话还是该减工具"。
    assert by_kind["tools"] > by_kind["messages"]


def test_估得准的时候照旧按减法来() -> None:
    """高估时才走兜底。估算靠谱时,减法比直接估更准,不该被替掉。"""
    messages = [{"role": "user", "content": "hi"}, _assistant("ok", input=12000, output=200)]
    parts = context_breakdown(messages, system_prompt="", tool_tokens=9000, window=32000)
    by_kind = {part["kind"]: part["tokens"] for part in parts["parts"]}
    assert by_kind["tools"] == 9000, "估算没问题时不该改动固定开销"
    assert by_kind["messages"] == 12200 - 9000


def test_还没有锚点时_对话就是消息本身() -> None:
    """一次都还没成功跑过(或供应商不报 usage)时,总量只是消息的估算,不含固定开销 ——
    这时再减一遍就会把对话减没。"""
    messages = [{"role": "user", "content": "很长的一段话" * 200}]
    parts = context_breakdown(messages, system_prompt="系统", tool_tokens=9000, window=32000)
    by_kind = {part["kind"]: part["tokens"] for part in parts["parts"]}
    assert by_kind["messages"] == context_tokens(messages) > 0
    assert by_kind["tools"] == 9000
