"""控制边**一律保留**,「谁该跑」照样不变 —— 这一条才是当初要保的东西。

## 现场

规范化把精确引用 `{{A.text}}` 升级成数据边之后,会把同一对节点间无 handle 的控制边当多余的折掉 —— 数据边本身
也排先后。当初这么做是为了让引擎判「该不该跑」判得对:engine.incoming_active 有控制边只看控制边,任一条来源跑了
就跑。T 的控制边只来自条件分支里的 A、另有一条数据边来自分支外的 B 时,折掉 A→T 确实把「A 跑了才跑」改成了
「A 或 B 跑了就跑」,条件为假、A 被跳过,T 照样拿着空的 A.text 跑了。

可维护者要的是**画出来的边都留着**(他要能看见,见 ADR 0063),而折边只能靠「折掉之后谁该跑正好不变」来兜底 ——
那取决于同一条边旁边有没有别的入边,同一张图里时有时无。于是这一条从「规范化折」改成「引擎明说」:

## 新口径

- **边一条不折。** 上面那几种场景里,控制边保存后都在(包括当初会被折掉的那两条)。
- **带路由语义的控制边说了算。** 目标节点上只要有一条条件节点的真 / 假出口,它就跑不跑由那一支定;同格上
  那些**已经有一条同向数据线**的普通控制边只定先后,不激活它 —— 折边当初折的就是这几条,引擎现在自己判。
  **没有同向数据线**的普通控制边照旧激活(同格上没有别的东西能排它,作者画它就是要这一格跑起来)。
  没有带路由的边时,全部控制边照旧算数(一条控制边都没有,才看数据边)。

下面每条场景的**判据(谁在 context 里、谁不在)和折边那会儿逐字相同**,变的只有「控制边在不在」。
"""

from __future__ import annotations

from tests.util import fresh_client, wait_status


def _graph(*, with_b: bool) -> dict:
    body = "{{B.text}}" if with_b else "固定的正文"
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"has_voice": "no"}}},
            {"id": "c", "type": "condition", "config": {"left": "{{start.has_voice}}", "op": "equals", "right": "yes"}},
            {"id": "A", "type": "template", "config": {"template": "口播稿"}},
            {"id": "B", "type": "template", "config": {"template": "画面"}},
            {"id": "T", "type": "notify", "config": {"title": "{{A.text}}", "body": body}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c"},
            {"id": "e2", "source": "c", "target": "A", "source_handle": "true"},
            {"id": "e3", "source": "start", "target": "B"},
            {"id": "e4", "source": "A", "target": "T"},
        ],
    }


def _save_and_run(graph: dict) -> tuple[dict, dict]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "分支", "graph": graph}).json()
    started = client.post(f"/api/workflows/{saved['id']}/run", json={"params": {}}).json()
    assert wait_status(client, started["id"]) == "succeeded"
    return saved["graph"], client.get(f"/api/jobs/{started['id']}").json()["result"]["context"]


def _pairs(graph: dict, kind: str) -> set[tuple[str, str]]:
    return {(edge["source"], edge["target"]) for edge in graph["edges"] if edge.get("kind", "control") == kind}


def test_T另有来自分支外B的数据_A到T的控制边留着_A被跳过时T也跳过() -> None:
    saved, context = _save_and_run(_graph(with_b=True))
    assert ("A", "T") in _pairs(saved, "control"), "作者画的边一律留,折掉就看不见「A 在 T 前面」"
    assert {("A", "T"), ("B", "T")} <= _pairs(saved, "data")
    assert "A" not in context and "T" not in context, "条件为假,A 被跳过,只从 A 那里拿值也只在 A 之后跑的 T 也该跳过"
    assert context["B"]["text"] == "画面"


def test_T的数据和控制都只来自A_控制边留着_判法不变() -> None:
    """当初这里折边是为了「A 没跑 T 就别跑」—— 保留控制边之后由控制边自己说了算,判出来一样(A 没跑,T 跳过)。"""
    saved, context = _save_and_run(_graph(with_b=False))
    assert ("A", "T") in _pairs(saved, "control"), "边留着;引擎看它决定 T 跑不跑(A 没跑就不跑)"
    assert ("A", "T") in _pairs(saved, "data")
    assert "T" not in context, "A 被跳过,只从 A 那里排先后的 T 照样跳过"


def test_T另有一条不带数据的普通控制边_两条控制边都留着_那一条没跑T照样跑() -> None:
    """T 的控制边一条来自分支里的 A(不带数据)、一条来自分支外的 B(另有数据边)。作者画的是「A 或 B 跑了就跑」,
    两条都是不带路由的普通控制边,所以两条都算数:B 跑了,T 就跑 —— 出镜版带货口播收尾那句是空的时,字幕、导出、
    交付不能整段没了。「不是只排先后」不等于「带路由」:A→T 没写 handle、A 也不是条件节点。"""
    graph = _graph(with_b=True)
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "{{B.text}}", "body": "固定的正文"}
    graph["edges"].append({"id": "e5", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert {("A", "T"), ("B", "T")} <= _pairs(saved, "control"), "两条都是普通控制边,一条都不折"
    assert ("B", "T") in _pairs(saved, "data")
    assert "A" not in context, "条件为假,A 被跳过"
    assert context["T"]["sent"], "B 跑了,T 照样跑"


def test_T另有条件的真出口_只排先后的控制边留着_由条件说了算() -> None:
    """条件为假 → 走「假」出口的 T 跑了;同格上那两条只排先后的控制边留着,但不把它们变成激活。"""
    graph = _graph(with_b=True)
    #: 标题取分支外的 B(A 被跳过时正文是空的,通知照样发得出去)。
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "{{B.text}}", "body": "{{A.text}}"}
    graph["edges"].append({"id": "e5", "source": "c", "target": "T", "source_handle": "false"})
    graph["edges"].append({"id": "e6", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert {("A", "T"), ("B", "T"), ("c", "T")} <= _pairs(saved, "control"), "三条控制边都在"
    assert "T" in context, "条件为假,走「假」出口的 T 跑了 —— 排先后的边没把它拉回「A 或 B 跑了就跑」"


def test_条件为真时走假出口的T不跑_排先后的边不激活它() -> None:
    """**这条钉的是引擎那半条规矩**(ADR 0063):目标上有条件节点的出口时,由那一支说了算。

    条件为真 → 「假」出口那一条不匹配;A 和 B 都跑了(它们各自的控制边都在),可 T 只挂在「假」那一支上,
    照样不跑。折边那会儿的图里 A→T / B→T 已经不在了,判出来是同一个结果 —— 引擎明说这一条之后,边留着
    也不会把 T 激活。少了它,出镜版带货口播「开场那句是空的就跳过出镜」、每一拍「没有画外音就不铺音轨」
    那两道门就形同虚设。
    """
    graph = _graph(with_b=True)
    next(node for node in graph["nodes"] if node["id"] == "start")["config"] = {"params": {"has_voice": "yes"}}
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "{{B.text}}", "body": "{{A.text}}"}
    graph["edges"].append({"id": "e5", "source": "c", "target": "T", "source_handle": "false"})
    graph["edges"].append({"id": "e6", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert {("A", "T"), ("B", "T"), ("c", "T")} <= _pairs(saved, "control"), "三条控制边都在"
    assert "A" in context and context["B"]["text"] == "画面", "走「真」出口的 A 和分支外的 B 都跑了"
    assert "T" not in context, "T 只挂在「假」出口上,条件为真就不跑 —— 排先后的边不激活它"


def test_普通控制边没有同向数据线时照旧激活它_哪怕目标另有条件的出口() -> None:
    """**另一半**:没有同向数据线的那条普通控制边不是「只排先后」,它照旧激活目标。

    同格上没有别的数据线能排它,作者画它就是要这一格跑起来 —— 官方模板 `reference_video_shots` 的
    `describe`(want_speech 的两个出口 + transcript_section→describe:要不要先转写再逐镜描述)、
    `highlight_shorts` 的 `cut_clips` 靠的都是它。一并当成"只排先后",这两格该跑的时候就不跑了。
    """
    graph = _graph(with_b=False)
    next(node for node in graph["nodes"] if node["id"] == "start")["config"] = {"params": {"has_voice": "yes"}}
    #: T 不引用 A / B 任何一个 —— 于是 B→T 上没有同向数据线,它是条"真的要它跑"的普通控制边。
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "固定的标题", "body": "固定的正文"}
    graph["edges"].append({"id": "e5", "source": "c", "target": "T", "source_handle": "false"})
    graph["edges"].append({"id": "e6", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert {("A", "T"), ("B", "T"), ("c", "T")} <= _pairs(saved, "control"), "三条控制边都在"
    assert not any(
        edge.get("kind") == "data" and edge["source"] == "B" and edge["target"] == "T" for edge in saved["edges"]
    ), "这一场要的就是「B→T 没有同向数据线」"
    assert context["A"]["text"] == "口播稿", "条件为真,走「真」出口的 A 跑了(但 T 不在那一支上)"
    assert context["B"]["text"] == "画面"
    assert context["T"]["sent"], "B 跑了,那条没有同向数据线的普通控制边照样激活 T"
