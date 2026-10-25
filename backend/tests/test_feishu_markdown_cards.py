"""飞书里的长正文用交互卡片(卡片 JSON 2.0 的 `markdown` 组件)渲染;短通知照旧是 `text`。

## 要钉住的是什么

智能体回复此前和任务回执一样走 `msg_type: "text"`,飞书客户端把 markdown **原样显示成源码**。
这一轮只改「长正文」那一类:回复与工作流运行结果发成 `interactive` 卡片,卡里是 **JSON 2.0**
(`schema: "2.0"`、`body.elements` 里一个 `markdown` 组件),正文一个字都不改。

**为什么是 2.0 而不是 1.0 的 `lark_md`:** 标题(`##`)、表格、引用只有 2.0 的 `markdown`
组件认(官方文档:富文本组件「支持渲染标题、表情、表格、图片、代码块、分割线等元素」,
表格语法「仅支持 JSON 2.0 结构」)。1.0 的 `lark_md` 不认这几样,发出去就是源码/兜底样式。

回执、绑定提示、看不了这类短通知仍然是 `text` —— 它们多一次卡片失败面,而换来的排版收益是零。

## 两道保险(必须)

- **v2 卡片发不出去 → 同一段内容用 `text` 重发**,并留下一句带原因的日志。消息不许凭空消失。
  **只保两层**:2.0 失败不再退回 1.0 的 `lark_md` —— 那等于给同一个内容多押一次注,而且 v1 再失败时
  仍然要落到 `text`,只是把"多久送到"拖长。见 `client.send_markdown` 的说明。
- **超长 → 按飞书 30 KB 的卡片上限分多张卡**,每张带 `（i/n）` 编号,拼起来等于原文。不静默截断。
  30 KB 是**按 v2 卡片的真实请求体**量的:2.0 的外壳(`schema` / `body`)与 JSON 转义都算在内。

打桩打在**传输层**(`httpx.MockTransport`):真的 `RetryingClient` / 请求体序列化 / `call_api`
都还在,只有"把 HTTP 发给谁"被换掉 —— 不连外网。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, FeishuBot
from app.integrations.feishu import client, inbound
from tests.util import fresh_client


@dataclass(frozen=True)
class _Bot:
    """`client` 只读这三格;令牌缓存按 id 分,所以每条用例给一个新的 id。"""

    id: str
    app_id: str = "cli_md"
    app_secret: str = "s"


class _Wire:
    """把出网换成按脚本回答的那一份,并把每次请求原样记下来。"""

    def __init__(self, monkeypatch, *, card_error: dict | None = None) -> None:
        self.seen: list[httpx.Request] = []
        self.card_error = card_error
        wire = self

        def handler(request: httpx.Request) -> httpx.Response:
            wire.seen.append(request)
            if request.url.path.endswith("/tenant_access_token/internal"):
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})
            if wire.card_error is not None and json.loads(request.content).get("msg_type") == "interactive":
                return httpx.Response(200, json=wire.card_error)
            return httpx.Response(200, json={"code": 0, "data": {"message_id": f"om_{len(wire.seen)}"}})

        class _Scripted(client.RetryingClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(client, "RetryingClient", _Scripted)

    def message_requests(self) -> list[httpx.Request]:
        return [
            request
            for request in self.seen
            if request.method == "POST" and request.url.path.endswith("/im/v1/messages")
        ]

    def messages(self) -> list[dict]:
        return [json.loads(request.content) for request in self.message_requests()]


def _card_of(message: dict) -> dict:
    assert message["msg_type"] == "interactive", message
    return json.loads(message["content"])


def _markdown_of(card: dict) -> str:
    """卡里那段正文:JSON 2.0 的 `body.elements` 里那个 `markdown` 组件。

    顺带钉住「不许是 1.0 的 `lark_md`」:2.0 卡片里根本没有 `elements` 这个顶层键,
    标题/表格/引用那几样正好是 1.0 不认的。
    """
    assert card.get("schema") == "2.0", card
    assert "elements" not in card, f"还是 1.0 的形状:{card}"
    elements = card["body"]["elements"]
    assert [element["tag"] for element in elements] == ["markdown"], elements
    return elements[0]["content"]


def _seeded_bot(client_http) -> dict:
    """直接落一行机器人,不走 `POST /api/feishu/bots` —— 那条路会顺手起一台**真去连飞书**的
    长连接子进程(`connections.start_or_report`),而这几条用例只关心发消息。"""
    ws = client_http.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws["id"], app_id="cli_md", app_secret="s3cret")
        db.add(bot)
        db.commit()
        return {"id": bot.id, "workspace_id": ws["id"]}


def _seed_assistant_reply(bot_id: str, chat_id: str, text: str) -> str:
    """造一条已经跑完的飞书会话 + 最后一条助手消息 —— `deliver_turn` 读的就是这两样。"""
    import time

    suffix = str(time.time_ns())
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        assert bot is not None
        session = AgentSession(
            workspace_id=bot.workspace_id,
            origin="feishu",
            external_key=f"feishu:{bot_id}:{chat_id}-{suffix}",
            title="飞书 · 测试",
        )
        db.add(session)
        db.flush()
        db.add(AgentMessage(session_id=session.id, role="assistant", content=text))
        db.commit()
        return session.id


# ---------------- ① 长正文 → interactive 卡片,JSON 2.0 的 markdown 组件,原文一字不改 ----------------


def test_智能体回复发成交互卡片_正文一字不改(monkeypatch) -> None:
    """`deliver_turn` 是智能体回复的出口:它必须发 `interactive`,卡里是 2.0 的 `markdown` 组件。"""
    client_http = fresh_client()
    bot = _seeded_bot(client_http)
    wire = _Wire(monkeypatch)
    reply = "## 结论\n\n- **重点**:已检查\n- 用时 `12s`\n\n> 下一句是链接:[素材库](https://example.com)"

    inbound.deliver_turn(_seed_assistant_reply(bot["id"], "oc_card", reply))

    messages = wire.messages()
    assert len(messages) == 1, messages
    card = _card_of(messages[0])
    assert card == {"schema": "2.0", "body": {"elements": [{"tag": "markdown", "content": reply}]}}


def test_send_markdown_单张卡的形状(monkeypatch) -> None:
    """卡片形状就是约定那一个:`schema: "2.0"` + `body.elements[0].tag == "markdown"`,正文原样。"""
    wire = _Wire(monkeypatch)
    text = "第一行 **粗体**\n第二行 [链接](https://example.com)"

    client.send_markdown(_Bot("b-shape"), "oc_1", text)

    messages = wire.messages()
    assert len(messages) == 1
    card = _card_of(messages[0])
    assert card["schema"] == "2.0"
    assert card["body"]["elements"][0]["tag"] == "markdown"
    assert _markdown_of(card) == text


def test_标题表格与引用原样进正文_渲染交给飞书(monkeypatch) -> None:
    """`## 小标题` / 表格行 / 引用不再被当成「不支持」:

    1.0 的 `lark_md` 认不了标题与表格(官方文档:表格语法「仅支持 JSON 2.0 结构」),
    所以它们此前要么显示成源码、要么被吞掉。2.0 的 `markdown` 组件把它们当语法收下,
    **我们这边一个字都不改** —— 怎么渲染是飞书的事,拆解 / 排版不归发送端。
    """
    wire = _Wire(monkeypatch)
    text = (
        "## 小标题\n"
        "\n"
        "| 项目 | 状态 |\n"
        "| --- | --- |\n"
        "| 卡片 | 已切到 2.0 |\n"
        "\n"
        "> 引用一句,行内换行也原样。\n"
    )

    client.send_markdown(_Bot("b-syntax"), "oc_5", text)

    messages = wire.messages()
    assert len(messages) == 1, messages
    card = _card_of(messages[0])
    content = _markdown_of(card)
    assert content == text, "正文不许被改写 / 重排"
    assert "## 小标题" in content
    assert "| 项目 | 状态 |" in content and "| --- | --- |" in content
    assert "> 引用一句" in content
    #: 整个卡片 JSON 里不该再出现 1.0 的写法。
    assert "lark_md" not in json.dumps(card, ensure_ascii=False)


# ---------------- ② v2 卡片发失败 → 自动降级成 text,日志里有原因(只有两层) ----------------


def test_卡片被拒时降级成文字重发_并记下原因(monkeypatch, caplog) -> None:
    """v2 卡片这条路失败(权限 / 卡片 JSON 被拒 / 网络),不能把这条回复弄丢。

    **只保两层**:`interactive`(2.0)失败之后就是 `text`,不再往 1.0 的 `lark_md` 退一步 ——
    两个请求,第三条不存在。日志里要有飞书自己那句话。
    """
    caplog.set_level(logging.WARNING)
    wire = _Wire(
        monkeypatch,
        card_error={"code": 230099, "msg": "Failed to create card content, ext=ErrCode: 200621"},
    )
    text = "## 结论\n\n| 项目 | 状态 |\n| --- | --- |\n| 卡片 | 发不出去也必须送到 |"

    sent_ids = client.send_markdown(_Bot("b-fallback"), "oc_2", text)

    assert sent_ids, "降级之后同样要有消息 id"
    messages = wire.messages()
    assert [one["msg_type"] for one in messages] == ["interactive", "text"], messages
    failed_card = _card_of(messages[0])
    assert _markdown_of(failed_card) == text, "先失败的必须是 v2 卡片本身(同一段正文)"
    assert json.loads(messages[1]["content"]) == {"text": text}, "降级要发同一段正文,一个字不改"
    #: 不能多出第三条(比如 v2 失败又退回 v1,再退到 text)。
    assert len(messages) == 2, messages
    reasons = [record.getMessage() for record in caplog.records if "card" in record.getMessage().lower()]
    assert reasons, "卡片失败必须在日志里留下原因"
    assert any("230099" in one for one in reasons), reasons
    assert any("200621" in one for one in reasons), reasons


def test_卡片构造失败也降级成文字(monkeypatch, caplog) -> None:
    """连卡片 JSON 都拼不出来(代码缺陷 / 上游改动)时,回复照样要送到。"""
    caplog.set_level(logging.WARNING)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(client, "markdown_chunks", lambda text: (_ for _ in ()).throw(RuntimeError("builder broke")))
    monkeypatch.setattr(client, "send_text", lambda bot, chat_id, text, **k: sent.append((chat_id, text)) or "om_t")

    ids = client.send_markdown(_Bot("b-buildfail"), "oc_2b", "原文")

    assert ids == ["om_t"]
    assert sent == [("oc_2b", "原文")]
    assert any("build failed" in record.getMessage() and "builder broke" in record.getMessage() for record in caplog.records)


def test_某一张卡的文字降级也失败时后面的卡继续发(monkeypatch) -> None:
    text = "\n\n".join(f"## 第 {index} 段\n" + ("长文字。" * 3000) for index in range(3))
    chunks = client.markdown_chunks(text)
    failed = 2
    cards: list[str] = []

    def card(bot, chat_id, payload, **kwargs):
        title = payload["header"]["title"]["content"]
        if title == f"（{failed}/{len(chunks)}）":
            raise client.FeishuError("feishuErr_sendCard", detail="boom")
        cards.append(title)
        return "om_card"

    def text_send(bot, chat_id, body, **kwargs):
        raise client.FeishuError("feishuErr_sendText", detail="also boom")

    monkeypatch.setattr(client, "send_card", card)
    monkeypatch.setattr(client, "send_text", text_send)

    client.send_markdown(_Bot("b-partial-fallback"), "oc_2d", text)

    assert len(cards) == len(chunks) - 1, "失败的这一张后面的卡不能被一起带走"


def test_分卡里某一张失败只把那一张降级(monkeypatch) -> None:
    """已发出去的卡不重发:哪一张失败就只把那一张换成文字,顺序不变。"""
    text = "\n\n".join(f"## 第 {index} 段\n" + ("长文字。" * 3000) for index in range(3))
    chunks = client.markdown_chunks(text)
    assert len(chunks) >= 3, len(chunks)
    failed = 2
    calls: list[tuple[str, str]] = []

    def card(bot, chat_id, payload, **kwargs):
        title = payload["header"]["title"]["content"]
        if title == f"（{failed}/{len(chunks)}）":
            raise client.FeishuError("feishuErr_sendCard", detail="boom")
        calls.append(("card", payload["body"]["elements"][0]["content"]))
        return "om_card"

    def text_send(bot, chat_id, body, **kwargs):
        calls.append(("text", body))
        return "om_text"

    monkeypatch.setattr(client, "send_card", card)
    monkeypatch.setattr(client, "send_text", text_send)

    client.send_markdown(_Bot("b-partial"), "oc_2c", text)

    kinds = [kind for kind, _ in calls]
    assert kinds.count("text") == 1, kinds
    assert kinds == ["card", "text"] + ["card"] * (len(chunks) - 2)
    label = f"（{failed}/{len(chunks)}）\n"
    bodies = [body.removeprefix(label) if kind == "text" else body for kind, body in calls]
    assert "".join(bodies) == text


# ---------------- ③ 超长 → 分多张卡,顺序与编号清楚,不截断 ----------------


def test_超长正文分多张卡_拼起来等于原文(monkeypatch) -> None:
    """飞书卡片请求体上限 30 KB:超过就分卡,而不是截断。"""
    wire = _Wire(monkeypatch)
    paragraphs = [f"## 第 {index} 段\n" + ("这是一段会被飞书卡片限制挡住的长文字。" * 300) for index in range(4)]
    text = "\n\n".join(paragraphs)
    assert len(text.encode("utf-8")) > client.CARD_PAYLOAD_MAX_BYTES

    client.send_markdown(_Bot("b-long"), "oc_3", text)

    messages = wire.messages()
    assert len(messages) >= 2, f"超长正文只发了一张卡:{len(messages)}"
    cards = [_card_of(one) for one in messages]
    bodies = [_markdown_of(card) for card in cards]
    assert "".join(bodies) == text, "分卡不许吞掉 / 改写任何一段正文"
    for index, (request, card) in enumerate(zip(wire.message_requests(), cards, strict=True), 1):
        #: 量**真正发出去的请求体**,飞书的上限是它(30 KB)。
        assert len(request.content) <= 30_000, len(request.content)
        title = card["header"]["title"]["content"]
        assert title == f"（{index}/{len(cards)}）", title


def test_引号与换行多的正文也按请求体大小分卡(monkeypatch) -> None:
    """JSON 转义会让同样的正文变大两成:只按正文字节分卡,代码块多的回复会在飞书那里撞上限。"""
    wire = _Wire(monkeypatch)
    text = ('```python\nprint("hello")\n```\n- **item** "quoted"\n') * 1500

    client.send_markdown(_Bot("b-quotes"), "oc_3b", text)

    requests = wire.message_requests()
    assert len(requests) >= 2, len(requests)
    for request in requests:
        assert len(request.content) <= 30_000, len(request.content)
    bodies = [_markdown_of(_card_of(json.loads(request.content))) for request in requests]
    assert "".join(bodies) == text


def test_29_KB_边界_刚好装下就一张卡_多一个字节就分两张(monkeypatch) -> None:
    """边界就在 `CARD_PAYLOAD_MAX_BYTES`:量的是 2.0 卡片发出去的那个**真实请求体**。

    2.0 的外壳(`schema` / `body`)与 JSON 转义都算在里面 —— 边界两侧各验一次,
    免得"分卡逻辑还在、但包装改了之后尺寸算错"这种偏移静默漏过去。
    """
    limit = client.CARD_PAYLOAD_MAX_BYTES
    low, high = 1, limit
    while low < high:
        middle = (low + high + 1) // 2
        if client.markdown_chunks("a" * middle) == ["a" * middle]:
            low = middle
        else:
            high = middle - 1
    fits = "a" * low
    assert client.markdown_chunks(fits) == [fits]
    assert len(client.markdown_chunks(fits + "a")) == 2

    wire = _Wire(monkeypatch)
    client.send_markdown(_Bot("b-edge-fit"), "oc_6", fits)
    first = wire.message_requests()
    assert len(first) == 1, "刚好装得下就该是一张卡"
    for request in first:
        assert len(request.content) <= 30_000, len(request.content)

    over = fits + "a"
    sent = client.send_markdown(_Bot("b-edge-over"), "oc_7", over)
    requests = wire.message_requests()[1:]
    assert len(requests) == len(sent) == 2, (len(requests), len(sent))
    for request in requests:
        assert len(request.content) <= 30_000, len(request.content)
    assert "".join(_markdown_of(_card_of(json.loads(request.content))) for request in requests) == over


def test_超长正文里没有换行的单行也会被切开(monkeypatch) -> None:
    """一整行超长(压缩过的 JSON、一大段没有句读)同样必须散成多张卡。"""
    wire = _Wire(monkeypatch)
    text = "a" * (client.CARD_PAYLOAD_MAX_BYTES * 2)
    client.send_markdown(_Bot("b-oneline"), "oc_4", text)

    bodies = [_markdown_of(_card_of(one)) for one in wire.messages()]
    assert len(bodies) >= 2
    assert "".join(bodies) == text


# ---------------- ④ 短通知仍然是 text ----------------

def test_短通知仍然发文字(monkeypatch) -> None:
    """「看不了这种消息」是回执类短通知 —— 保持 text,少一次卡片失败面。"""
    client_http = fresh_client()
    bot = _seeded_bot(client_http)
    wire = _Wire(monkeypatch)

    inbound.handle_incoming(
        bot["id"], "oc_voice", "msg-voice", "ou_sender", message_type="audio", content_json="{}"
    )

    messages = wire.messages()
    assert len(messages) == 1, messages
    assert messages[0]["msg_type"] == "text"
    assert "看不了语音" in json.loads(messages[0]["content"])["text"]
