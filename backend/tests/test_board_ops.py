"""智能体改画板走的是**细粒度算子**,不是重写整份画布。

让模型吐回整份 canvas,在稍微复杂一点的画板上必然出错:漏掉几项、或者把用户刚拖好的位置
全部推平 —— 而这两种错都不报错,用户只会发现"我的东西不见了"。所以它表达意图,服务端落到
当前画布上。

这些用例钉住算子本身的规矩;产物能不能存由 normalize_canvas 说了算,两者分工不重叠。
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.domain.boards.canvas import DEFAULT_SIZE
from app.domain.boards.ops import apply_board_ops
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


def test_已经连着的两项再连一次不会多出第二根线() -> None:
    """画布上手拉的线 id 是 React Flow 起的(不是 e-a-b)。智能体再 connect 同一对时按 id 查重
    查不出来,于是多出第二根:下游从上游拿文字时这段话被拼进提示词两遍。连线表达的是「这两项
    有关系」,同一对连两次不多表达任何东西。"""
    out = apply_board_ops(
        _canvas(
            [{"id": "a", "kind": "note", "x": 0, "y": 0, "text": "一只猫"}, {"id": "b", "kind": "image", "x": 300, "y": 0}],
            [{"id": "xy-edge__a-b", "source": "a", "target": "b"}],
        ),
        [{"kind": "connect", "source": "a", "target": "b"}],
    )
    assert out["edges"] == [{"id": "xy-edge__a-b", "source": "a", "target": "b"}]


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
    """RATCHET:前端 boardNodes.DEFAULT_SIZE 和后端 boards/canvas.DEFAULT_SIZE 必须一致。

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
            #: 每个键(种类名、width、height)都加上引号 —— 逐个 replace 的话,加一种格子就得记得来这里补一行。
            re.sub(r"(\w+):", r"'\1':", body.replace("\n", " "))
        ).items()
    }
    assert front == DEFAULT_SIZE, f"两端的默认大小分了岔:前端 {front} / 后端 {DEFAULT_SIZE}"


def test_智能体改画板走确认卡_并且写坏的算子在批准前就失败() -> None:
    """写操作一律先出卡:画板是用户攒想法的地方,替他改之前得让他看一眼。

    而且**开卡时就干跑一遍** —— 算子写坏了要在这一刻失败,不能等用户点了「同意」才报错:
    那时他以为自己批准的是一件做得成的事。
    """
    from app.core.db import SessionLocal
    from app.domain.agent.confirmable import tool_spec
    from app.domain.agent.confirmations import ConfirmationError, request_confirmation
    from tests.util import fresh_client

    assert tool_spec("edit_board").permission == "edit"

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
        actor_id=None,
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
            actor_id=None,
        requested_by="agent",
        )
    db.close()


def _fed_board() -> dict:
    """上游一张图 A 连到下游视频 V;V 的首帧是顺着线挂上的 A,尾帧是手动挂的。"""
    return {
        "items": [
            {"id": "A", "kind": "image", "x": 0, "y": 0, "asset_id": "a1"},
            {"id": "V", "kind": "video", "x": 400, "y": 0, "form": {"prompt": "动起来", "source_assets": [
                {"asset_id": "a1", "role": "first_frame", "from": "A"},
                {"asset_id": "m1", "role": "last_frame"},
            ]}},
        ],
        "edges": [{"id": "e1", "source": "A", "target": "V"}],
    }


@pytest.mark.parametrize("operation", [
    {"kind": "remove_item", "item_id": "A"},
    {"kind": "remove_edge", "edge_id": "e1"},
])
def test_智能体删掉上游那一格或那根线_下游槽位里从那条线来的那份跟着摘掉(operation) -> None:
    """前端画布上删线有这条规则,而智能体改画板(edit_board)在服务端落库时没有 —— 下游表单里那份
    引用原样留着,下次打开面板还挂在首帧上,点生成照样发出去。手动挂的照留。"""
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": _fed_board()}).json()["id"]

    from app.core.db import SessionLocal
    from app.domain.agent.confirmations import approve_confirmation, request_confirmation

    with SessionLocal() as db:
        card = request_confirmation(
            db, workspace_id=ws, tool="edit_board",
            payload={"board_id": board_id, "operations": [operation]}, actor_id=None, requested_by="agent",
        )
        done = approve_confirmation(db, card)
        assert done.status == "executed", done.error

    canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]
    video = next(one for one in canvas["items"] if one["id"] == "V")
    assert video["form"]["source_assets"] == [{"asset_id": "m1", "role": "last_frame"}]


def test_上游换了一份素材_下游挂着的旧那份不再算数() -> None:
    board = _fed_board()
    board["items"][0]["asset_id"] = "b1"
    video = normalize_canvas(board)["items"][1]
    assert video["form"]["source_assets"] == [{"asset_id": "m1", "role": "last_frame"}]


def test_线还在就原样留着_同一份再存一遍结果一样() -> None:
    once = normalize_canvas(_fed_board())
    assert once["items"][1]["form"]["source_assets"] == _fed_board()["items"][1]["form"]["source_assets"]
    assert normalize_canvas(once) == once


def test_客户端存回来一份线已经断了的旧快照_照样摘掉() -> None:
    """判据只看这一份画布自己,不拿「上一次」去比 —— 旧快照再存回来,结果和第一次一样。"""
    board = _fed_board()
    board["edges"] = []
    assert normalize_canvas(board)["items"][1]["form"]["source_assets"] == [{"asset_id": "m1", "role": "last_frame"}]


def test_给一格起名_改名_取消名字() -> None:
    """名字是每一格都有的 `title`。智能体认格子、用户看节点上方那一行,读的都是它。"""
    base = _canvas([
        {"id": "i1", "kind": "image", "x": 0, "y": 0},
        {"id": "f1", "kind": "frame", "x": 0, "y": 300, "title": "第一幕"},
    ])
    out = apply_board_ops(base, [
        {"kind": "add_item", "type": "video", "item_id": "v1", "title": "  开场  镜头 "},
        {"kind": "set_title", "item_id": "i1", "title": "主视觉"},
        {"kind": "set_title", "item_id": "f1", "title": ""},
    ])
    canvas = normalize_canvas(out)
    items = {one["id"]: one for one in canvas["items"]}
    assert items["i1"]["title"] == "主视觉"
    assert items["v1"]["title"] == "开场 镜头", "名字是一行字:空白收成单个空格"
    assert "title" not in items["f1"], "空名字 = 不要名字了,退回显示种类名"

    with pytest.raises(BoardDomainError):
        apply_board_ops(base, [{"kind": "set_title", "item_id": "无", "title": "x"}])


def test_智能体改名经确认卡落到画板上_读回来带着名字() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "a", "kind": "image", "x": 0, "y": 0},
        {"id": "b", "kind": "image", "x": 300, "y": 0},
    ], "edges": []}}).json()["id"]

    card = client.post("/api/confirmations", json={
        "workspace_id": ws,
        "tool": "edit_board",
        "requested_by": "agent",
        "payload": {"board_id": board_id, "operations": [
            {"kind": "set_title", "item_id": "a", "title": "猫 · 正面"},
            {"kind": "set_title", "item_id": "b", "title": "猫 · 侧面"},
        ]},
    })
    assert card.status_code == 200, card.text
    approved = client.post(f"/api/confirmations/{card.json()['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")

    # get_board(MCP)读的就是这份:两张同是「图片」的格子,靠名字分得开。
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    assert [one.get("title") for one in items] == ["猫 · 正面", "猫 · 侧面"]

    # 名字太长:开卡时干跑就拒,不等批准。
    too_long = client.post("/api/confirmations", json={
        "workspace_id": ws,
        "tool": "edit_board",
        "requested_by": "agent",
        "payload": {"board_id": board_id, "operations": [{"kind": "set_title", "item_id": "a", "title": "长" * 121}]},
    })
    assert too_long.status_code >= 400
