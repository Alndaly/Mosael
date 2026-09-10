"""正文写 `@名字`,id 走结构化字段。

名字会重、会改、会带空格 —— 拿它当标识迟早出事;而把 32 位十六进制塞进句子,会把真正的
那句话挤没。所以两件事分开:模型读到的是「把 @运镜练习 改长一点」,要动手时从清单里拿 id。

另一半是**发出去之后还得看得见**:body_document 落进 payload,气泡照它把引用画回胶囊,
而不是把 `@名字` 当成一串普通的字 —— 发送这个动作本身不该把用户刚放进去的结构抹平。
"""

from __future__ import annotations

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
