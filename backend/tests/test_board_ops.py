"""智能体改画板走的是**细粒度算子**,不是重写整份画布。

让模型吐回整份 canvas,在稍微复杂一点的画板上必然出错:漏掉几项、或者把用户刚拖好的位置
全部推平 —— 而这两种错都不报错,用户只会发现"我的东西不见了"。所以它表达意图,服务端落到
当前画布上。

这些用例钉住算子本身的规矩;产物能不能存由 normalize_canvas 说了算,两者分工不重叠。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.domain.board_ops import DEFAULT_SIZE, apply_board_ops
from app.domain.boards import BoardDomainError, normalize_canvas

RATCHET = True


def _canvas(items=None, edges=None) -> dict:
    return {"items": list(items or []), "edges": list(edges or [])}


def test_一批算子按顺序落下去() -> None:
    """add 之后紧跟着 connect 要能用 —— 后面的算子看得见前面新加的项。"""
    out = apply_board_ops(
        _canvas(),
        [
            {"kind": "add_item", "type": "note", "item_id": "n1", "x": 0, "y": 0, "text": "开场"},
            {"kind": "add_item", "type": "image", "item_id": "i1", "x": 300, "y": 0},
            {"kind": "connect", "source": "n1", "target": "i1"},
        ],
    )
    assert [one["id"] for one in out["items"]] == ["n1", "i1"]
    assert out["edges"] == [{"id": "e-n1-i1", "source": "n1", "target": "i1"}]
    # 产物必须存得下 —— 算子层和校验层各管一段,但接得上。
    normalize_canvas(out)


def test_不给坐标就往右边摆而不是摞在原点() -> None:
    """三项都落在原点的话,智能体加完东西用户看到的是一叠卡片。"""
    out = apply_board_ops(
        _canvas([{"id": "a", "kind": "note", "x": 0, "y": 0, "width": 220}]),
        [{"kind": "add_item", "type": "note"}, {"kind": "add_item", "type": "note"}],
    )
    xs = [one["x"] for one in out["items"]]
    assert len(set(xs)) == 3, f"新加的项摞在一起了:{xs}"
    assert xs[1] > 220


def test_删掉一项时连着它的线一起走() -> None:
    """留着悬空的线的话,normalize_canvas 会拒掉**整份**画布 —— 一次「删掉这张图」
    变成一句用户看不懂的报错,而且别的改动也一起没了。"""
    out = apply_board_ops(
        _canvas(
            [{"id": "a", "kind": "note", "x": 0, "y": 0}, {"id": "b", "kind": "image", "x": 300, "y": 0}],
            [{"id": "e1", "source": "a", "target": "b"}],
        ),
        [{"kind": "remove_item", "item_id": "b"}],
    )
    assert [one["id"] for one in out["items"]] == ["a"]
    assert out["edges"] == []
    normalize_canvas(out)


def test_算子写错了当场拒绝() -> None:
    cases = [
        [{"kind": "add_item", "type": "sticker"}],           # 没这种项
        [{"kind": "set_text", "item_id": "nope", "text": "x"}],  # 项不存在
        [{"kind": "connect", "source": "a", "target": "a"}],  # 连到自己
        [{"kind": "remove_edge", "edge_id": "nope"}],
        [{"kind": "教它飞", "item_id": "a"}],
    ]
    base = _canvas([{"id": "a", "kind": "note", "x": 0, "y": 0}])
    for operations in cases:
        with pytest.raises(BoardDomainError):
            apply_board_ops(base, operations)


def test_原画布不被就地改动() -> None:
    """算子作用在副本上 —— 就地改的话,中途某一条算子失败会留下改了一半的画布。"""
    base = _canvas([{"id": "a", "kind": "note", "x": 0, "y": 0}])
    with pytest.raises(BoardDomainError):
        apply_board_ops(base, [{"kind": "set_text", "item_id": "a", "text": "改了"}, {"kind": "remove_edge", "edge_id": "无"}])
    assert base["items"][0].get("text") is None


def test_新建的默认大小两端是同一组数() -> None:
    """RATCHET:前端 boardNodes.DEFAULT_SIZE 和后端 board_ops.DEFAULT_SIZE 必须一致。

    智能体加的项比手动加的小一圈,看起来就像两种不同的东西。这是一份**跨栈手抄的表**,
    没有编译期约束能发现它们分了岔 —— 所以在这里比对。
    """
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "frontend/src/features/boards/boardNodes.tsx"
    ).read_text(encoding="utf-8")
    body = source.split("DEFAULT_SIZE: Record<BoardItem[\"kind\"], { width: number; height: number }> = ", 1)[1]
    body = body.split("};", 1)[0] + "}"
    #: 直接读那段字面量而不是正则找数字 —— 正则会把注释里的数字也捞进来。
    front = {
        key: (int(value["width"]), int(value["height"]))
        for key, value in ast.literal_eval(
            body.replace("{ width:", "{'width':").replace(", height:", ", 'height':").replace("\n", " ")
            .replace("note:", "'note':").replace("image:", "'image':").replace("video:", "'video':")
            .replace("audio:", "'audio':").replace("frame:", "'frame':")
        ).items()
    }
    assert front == DEFAULT_SIZE, f"两端的默认大小分了岔:前端 {front} / 后端 {DEFAULT_SIZE}"


def test_智能体改画板走确认卡_并且写坏的算子在批准前就失败() -> None:
    """写操作一律先出卡:画板是用户攒想法的地方,替他改之前得让他看一眼。

    而且**开卡时就干跑一遍** —— 算子写坏了要在这一刻失败,不能等用户点了「同意」才报错:
    那时他以为自己批准的是一件做得成的事。
    """
    from app.core.db import SessionLocal
    from app.domain.agent.confirmations import ConfirmationError, TOOL_DEFS, request_confirmation
    from tests.util import fresh_client

    assert TOOL_DEFS["edit_board"]["permission"] == "edit"

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {"items": [{"id": "a", "kind": "note", "x": 0, "y": 0}], "edges": []},
        },
    ).json()["id"]

    db = SessionLocal()
    ok = request_confirmation(
        db,
        workspace_id=ws,
        tool="edit_board",
        payload={"board_id": board_id, "operations": [{"kind": "set_text", "item_id": "a", "text": "改好的"}]},
        requested_by="agent",
    )
    assert ok.status == "pending", "写画板居然没出确认卡"

    # 指向一个不存在的项:必须当场拒,而不是开出一张点了会炸的卡。
    with pytest.raises(ConfirmationError):
        request_confirmation(
            db,
            workspace_id=ws,
            tool="edit_board",
            payload={"board_id": board_id, "operations": [{"kind": "set_text", "item_id": "无", "text": "x"}]},
            requested_by="agent",
        )
    db.close()
