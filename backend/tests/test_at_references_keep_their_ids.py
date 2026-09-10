"""正文写 `@名字`,id 走结构化字段。

名字会重、会改、会带空格 —— 拿它当标识迟早出事;而把 32 位十六进制塞进句子,会把真正的
那句话挤没。所以两件事分开:模型读到的是「把 @运镜练习 改长一点」,要动手时从清单里拿 id。

另一半是**发出去之后还得看得见**:body_document 落进 payload,气泡照它把引用画回胶囊,
而不是把 `@名字` 当成一串普通的字 —— 发送这个动作本身不该把用户刚放进去的结构抹平。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.domain.agent import host


def test_引用清单说得出是谁_去哪儿读() -> None:
    text = host.references_context(
        [
            {"kind": "note", "id": "n1", "name": "mosael"},
            {"kind": "asset", "id": "a1", "name": "运镜练习.mp4"},
            {"kind": "workflow", "id": "w1", "name": "口播整理"},
            {"kind": "board", "id": "b1", "name": "故事板"},
        ]
    )
    # 名字和 id 对得上
    assert "「mosael」id=n1" in text
    assert "「运镜练习.mp4」id=a1" in text
    # **说出用哪个工具** —— 只给 id 的话,模型得先猜"笔记该用哪个工具",猜错就是一轮白跑。
    assert "read_note" in text
    assert "analyze_asset" in text
    assert "get_workflow" in text
    assert "get_board" in text


def test_没有引用就不挂一段空清单() -> None:
    assert host.references_context([]) == ""
    assert host.references_context(None) == ""


def test_缺id的条目直接丢掉() -> None:
    # 没有 id 的引用对模型毫无用处 —— 列出来只会让它拿一个空串去调工具。
    assert host.references_context([{"kind": "note", "name": "无名"}]) == ""


def test_落库的正文里没有id() -> None:
    from app.api.schemas import AgentMessageCreate

    body = AgentMessageCreate(
        content="把 @运镜练习 改长一点",
        references=[{"kind": "asset", "id": "a1", "name": "运镜练习"}],
        body_document={"type": "doc", "content": []},
    )
    # content 是**用户在对话里看到的**那份:它只有名字。
    assert "a1" not in body.content
    assert body.references[0].id == "a1"
    assert body.body_document is not None


def test_清单里点名的工具真的存在() -> None:
    """引用清单会告诉模型「用 read_note 读」—— 那个名字必须真的是一个工具。

    这是一处**跨文件的耦合**:名字写在 host._REFERENCE_HOW 里,而工具定义在 mcp_server.py。
    改名的一方不会知道另一方在引用它,而错了也不报错 —— 模型会去调一个不存在的工具,
    白跑一轮,然后大概率自己编一个理由继续往下走。

    (这四个名字当初是我按命名习惯猜的,恰好全中。这条用例把"恰好"换成"一定"。)
    """
    import mcp_server

    for _label, tool in host._REFERENCE_HOW.values():
        if not tool:
            continue
        assert callable(getattr(mcp_server, tool, None)), f"{tool} 不是 mcp_server 里的工具"


def test_删掉的对象明说已不存在(tmp_path) -> None:
    """名字是发送那一刻抄下来的快照,而对象会改名、会被删。

    给模型一个会 404 的 id,它白跑一轮之后多半会自己编个理由继续往下走 —— 那比直接
    告诉它"这个没了"坏得多。
    """
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    board = client.post("/api/boards", json={"workspace_id": ws["id"], "name": "故事板"}).json()

    with SessionLocal() as db:
        text = host.references_context(
            [
                {"kind": "board", "id": board["id"], "name": "旧名字"},
                {"kind": "board", "id": "没有这个", "name": "幽灵"},
            ],
            db=db,
            workspace_id=ws["id"],
        )

    # 改过名的用**库里当前的名字**:拿旧名字跟模型说话,它会照着那个名字去找,找不到。
    assert "「故事板」" in text
    assert "旧名字" not in text
    # 已经删了的明说,而且不给 id。
    assert "「幽灵」已不存在" in text
    assert "没有这个" not in text


def test_别的工作区的_id_当作不存在(tmp_path) -> None:
    """引用是前端交上来的。一条消息不该因为塞了一个别处的 id,就让模型知道那边有什么。"""
    from tests.util import fresh_client

    client = fresh_client()
    mine = client.post("/api/workspaces", json={"name": "我的"}).json()
    theirs = client.post("/api/workspaces", json={"name": "别人的"}).json()
    board = client.post("/api/boards", json={"workspace_id": theirs["id"], "name": "机密"}).json()

    with SessionLocal() as db:
        text = host.references_context(
            [{"kind": "board", "id": board["id"], "name": "机密"}], db=db, workspace_id=mine["id"]
        )

    assert "已不存在" in text
    assert board["id"] not in text


def test_排队发出的那条也带着引用清单() -> None:
    """agent 正忙时消息会先排队,晚一点由后台线程跑 —— 那条也得带上引用。

    这处漏过一次:排队那条只补了 context 和信封,引用清单没补。落库的 payload 里有引用、
    气泡照它把胶囊画了回来,**模型收到的却是另一份** —— 「@运镜练习」在它眼里只是四个字,
    一个 id 都没有。这种漏没有任何报错:模型会去搜一个同名的,或者干脆编一个理由往下走。

    所以两条路现在共用 user_prompt,这条钉的就是"共用"这件事本身。
    """
    payload = {
        "queued": True,
        "references": [{"kind": "asset", "id": "a1", "name": "运镜练习"}],
        "context": "先看看这个",
    }
    queued = host.user_prompt("把 @运镜练习 改长一点", payload)
    direct = host.user_prompt("把 @运镜练习 改长一点", {"references": payload["references"], "context": payload["context"]})

    assert queued == direct
    assert "id=a1" in queued
    assert "analyze_asset" in queued
    assert "先看看这个" in queued


def test_排队的路径真的走的是那一个函数() -> None:
    """上一条只证明函数对;这条盯着调用点 —— 漏掉的从来是"忘了调",不是"调错了"。"""
    import inspect

    drain = inspect.getsource(host._drain_queue_locked)
    assert "user_prompt(" in drain, "排队这条路又自己拼 prompt 了"
    assert "references_context(" not in drain, "拼法应当只有 user_prompt 一处"
