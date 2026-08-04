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
