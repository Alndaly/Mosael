"""跨会话通知:信封给模型,正文给人。

notify_agent_session 发来的消息此前把信封拼进了 `content`:

    【来自另一个智能体会话的通知】发起会话 id:5b99d040243b4fdabc4ba5b3ef03430d

    请报告一下你会话里最近在讨论什么。

而 `content` 正是用户在对话里看到的那一份 —— 于是界面上凭空多出一行方括号标签加一串 32 位
十六进制,两样都是写给模型的东西。「谁发来的」界面有更好的表达(来源抬头 + 对方会话标题)。

拆开之后要同时成立两件事,这里各钉一条:模型**仍然**收得到那句话(不然它不知道这是别的会话
发来的,会当成用户在说话),而库里那份正文是干净的。
"""

from __future__ import annotations

from app.ai.agent.host import agent_notice_envelope


def test_信封进提示词而不进正文() -> None:
    origin = "5b99d040243b4fdabc4ba5b3ef03430d"
    body = "请报告一下你会话里最近在讨论什么。"
    prompt = agent_notice_envelope(body, origin)

    assert body in prompt, "模型收到的那份把原话弄丢了"
    assert origin in prompt, "模型收不到是哪个会话发来的 —— 它会当成用户在说话"
    assert prompt.startswith("【"), "信封不在开头,模型可能读成正文的一部分"


def test_MCP那侧不再自己拼信封() -> None:
    """信封只有一个产地。两处都拼的话,用户会看到它两次;都不拼则模型一次都收不到。"""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "mcp_server.py").read_text(encoding="utf-8")
    body = source[source.index("def notify_agent_session"):]
    body = body[: body.index("\ndef ")]
    assert "【来自另一个智能体会话的通知】" not in body, "notify_agent_session 又开始自己拼信封了"
    assert '"content": text' in body, "发出去的正文不是原样文本"
    assert '"origin_session_id"' in body, "来源没走结构化字段"
