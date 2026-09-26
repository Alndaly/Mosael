"""智能体用画板上的能力(ADR 0021 P3,ADR 0025 修订「能力住在内容格上」):写一格的一项能力的设置、
给空格子挂生成器、看有哪些、替人点运行。

钉住三件事:
1. edit_board 写下的表单,开卡时就按**和界面、运行同一张注册表**检查 —— 工具在不在(按开卡的人)、
   是不是这种格子的能力 / 填法、字段有没有、绑定接不接得上(有线、种类对);没有单独的工具格可放;
2. list_board_producers 只列这个人自己接的插件工具,说清每一项挂在哪、宿主的内容填进哪个字段;
3. run_board_item 走的是界面点运行的同一个 producers.run:点名宿主上的一项能力,或跑那一格自己的生成器;
   只读的直接跑(卡留痕但不等人),花钱或对外的等人批准,用的是批准者自己的连接;拒了就什么都不跑。
"""

from __future__ import annotations

import pytest

import mcp_server
from tests.test_board_producers import SHOUT, _connect, _derived, _install_plugin, _me, _settled
from tests.util import fresh_client, second_client

TRANSLATE = "node:translate"
PAINT = "node:plugin.dev.test.boardtools.paint"
MANY = "node:plugin.dev.test.boardtools.many"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, items: list[dict], edges: list[dict] | None = None) -> str:
    created = client.post("/api/boards", json={
        "workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": edges or []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _card(client, ws: str, tool: str, payload: dict):
    return client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": tool, "requested_by": "agent", "payload": payload})


def _edit(client, ws: str, board_id: str, operations: list[dict]):
    return _card(client, ws, "edit_board", {"board_id": board_id, "operations": operations})


def _items(client, ws: str, board_id: str) -> dict[str, dict]:
    canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]
    return {one["id"]: one for one in canvas["items"]}


def _settle_card(client, card_id: str) -> dict:
    from app.domain.agent.autopilot import wait_for_idle_autopilot

    assert wait_for_idle_autopilot(10.0)
    return client.get(f"/api/confirmations/{card_id}").json()


# ── edit_board:写能力的设置、挂生成器 ─────────────────────────────────────────


def test_智能体在便签上写翻译的设置_宿主自己的表单不动() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hello"}])

    card = _edit(client, ws, board_id, [
        {"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "config": {"target_lang": "en"}},
    ])
    assert card.status_code == 200, card.text
    #: 开卡时按注册表判了这是一项能力,写回算子上(调用方自己说的不算)。
    assert card.json()["payload"]["operations"][0]["ability"] is True
    done = client.post(f"/api/confirmations/{card.json()['id']}/approve").json()
    assert done["status"] == "executed", done.get("error")

    note = _items(client, ws, board_id)["n1"]
    assert note["kind"] == "note" and note["text"] == "hello"
    assert note["form"] == {"abilities": {TRANSLATE: {"config": {"target_lang": "en"}, "bindings": {}}},
                            "producer": "write"}
    assert list(note["form"])[-1] == "producer", "产出者排在表单最后,和界面、运行写的同一个样子"


@pytest.mark.parametrize(("operations", "says"), [
    #: 没有单独的工具格可放。
    ([{"kind": "add_item", "type": "action", "item_id": "t1", "producer": TRANSLATE}], "action"),
    #: 没有这个工具。
    ([{"kind": "set_form", "item_id": "n1", "producer": "node:no_such_node"}], "no_such_node"),
    #: 内置的写字/生成的表单是面板的形状,不由智能体写。
    ([{"kind": "set_form", "item_id": "n1", "producer": "write"}], "write"),
    #: 翻译是便签 / 文档的能力,不是图片格的。
    ([{"kind": "set_form", "item_id": "i1", "producer": TRANSLATE, "config": {"target_lang": "en"}}], "translate"),
    #: 能力不能当一格自己的产出者。
    ([{"kind": "add_item", "type": "note", "item_id": "n2", "producer": TRANSLATE}], "n2"),
    #: 工具没有这个字段。
    ([{"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "config": {"lang": "en"}}], "lang"),
    #: 宿主的内容填的那个字段不是设置 —— 它就是宿主。
    ([{"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "config": {"text": "别的字"}}], "text"),
    ([{"kind": "connect", "source": "n9", "target": "n1"},
      {"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "bindings": {"text": [{"from": "n9"}]}}], "text"),
    #: 声明成数字的字段填的不是数。
    ([{"kind": "set_form", "item_id": "v1", "producer": "node:video_to_gif", "config": {"fps": "好多"}}], "帧率"),
    #: 流程和数据处理的节点不在画板上(归工作流)。
    ([{"kind": "set_form", "item_id": "n1", "producer": "node:text_transform"}], "text_transform"),
    #: 固定选项的字段不接上游。
    ([{"kind": "connect", "source": "n9", "target": "n1"},
      {"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "bindings": {"target_lang": [{"from": "n9"}]}}],
     "target_lang"),
    #: 分组框、文档这种格子没有能这样写的自己的表单。
    ([{"kind": "add_item", "type": "frame", "item_id": "f1", "producer": "node:video_to_gif"}], "f1"),
])
def test_写坏的表单在开卡时就拒(operations: list[dict], says: str) -> None:
    from tests.util import seed_assets

    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"a-1": "image", "v-1": "video"})
    board_id = _board(client, ws, [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hello"},
        {"id": "n9", "kind": "note", "x": 0, "y": 600, "text": "别的"},
        {"id": "i1", "kind": "image", "x": 0, "y": 300, "asset_id": "a-1"},
        {"id": "v1", "kind": "video", "x": 400, "y": 300, "asset_id": "v-1"},
    ])
    refused = _edit(client, ws, board_id, operations)
    assert refused.status_code == 422, refused.text
    assert says in refused.json()["detail"]
    assert not client.get("/api/confirmations", params={"workspace_id": ws}).json(), "说不通的改动开出了卡"


def test_set_form_能力的设置逐键合并_绑定逐字段替换_别的几项和宿主自己的表单不动() -> None:
    from app.domain.boards import BoardDomainError
    from app.domain.boards.ops import apply_board_ops

    base = {"items": [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "a"},
        {"id": "v1", "kind": "video", "x": 300, "y": 0, "asset_id": "clip", "form": {
            "abilities": {
                "node:plugin.x.mux": {"config": {"level": "high", "engine": "ai", "model": "m"},
                                      "bindings": {"voice": [{"from": "n1"}]}},
                "node:video_to_gif": {"config": {"fps": 12}},
            },
            "producer": "generate"}},
    ], "edges": [{"id": "e1", "source": "n1", "target": "v1"}]}

    out = apply_board_ops(base, [{"kind": "set_form", "item_id": "v1", "producer": "node:plugin.x.mux", "ability": True,
                                  "config": {"engine": "google", "model": None}, "bindings": {"voice": []}}])
    form = next(one for one in out["items"] if one["id"] == "v1")["form"]
    assert form == {"abilities": {
        "node:plugin.x.mux": {"config": {"level": "high", "engine": "google"}, "bindings": {}},
        "node:video_to_gif": {"config": {"fps": 12}},
    }, "producer": "generate"}

    #: 一项还没存过设置的能力:从空的开始,写在同一个 `abilities` 里。
    fresh = apply_board_ops(base, [{"kind": "set_form", "item_id": "n1", "producer": TRANSLATE, "ability": True,
                                    "config": {"target_lang": "ja"}}])
    assert next(one for one in fresh["items"] if one["id"] == "n1")["form"] == {
        "abilities": {TRANSLATE: {"config": {"target_lang": "ja"}, "bindings": {}}}}

    #: 空格子换生成器:它自己的表单从头来,能力的设置归这一格,留着。
    switched = apply_board_ops({"items": [{"id": "i1", "kind": "image", "x": 0, "y": 0, "form": {
        "prompt": "猫", "abilities": {"node:x": {"config": {}}}, "producer": "generate"}}], "edges": []},
        [{"kind": "set_form", "item_id": "i1", "producer": PAINT, "config": {"prompt": "狗"}}])
    assert switched["items"][0]["form"] == {"config": {"prompt": "狗"}, "bindings": {},
                                            "abilities": {"node:x": {"config": {}}}, "producer": PAINT}

    with pytest.raises(BoardDomainError):
        apply_board_ops(base, [{"kind": "set_form", "item_id": "n1", "config": {"target_lang": "en"}}])
    with pytest.raises(BoardDomainError):
        apply_board_ops(base, [{"kind": "set_form", "item_id": "v1", "producer": "generate", "ability": True}])


def test_set_form_经确认卡落库_绑定要有线(tmp_path) -> None:
    """空格子上的生成器接上游便签当提示词:线要先连上。"""
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "猫"},
        {"id": "i1", "kind": "image", "x": 300, "y": 0},
    ])

    #: n1 没连过来:拒。
    refused = _edit(client, ws, board_id, [{"kind": "set_form", "item_id": "i1", "producer": PAINT,
                                           "bindings": {"prompt": [{"from": "n1"}]}}])
    assert refused.status_code == 422 and "n1" in refused.json()["detail"]

    card = _edit(client, ws, board_id, [
        {"kind": "connect", "source": "n1", "target": "i1"},
        {"kind": "set_form", "item_id": "i1", "producer": PAINT, "bindings": {"prompt": [{"from": "n1"}]}},
    ])
    assert card.status_code == 200, card.text
    assert card.json()["payload"]["operations"][1]["ability"] is False, "生成器是这一格自己的产出者,不是一项能力"
    assert client.post(f"/api/confirmations/{card.json()['id']}/approve").json()["status"] == "executed"
    assert _items(client, ws, board_id)["i1"]["form"] == {
        "config": {}, "bindings": {"prompt": [{"from": "n1"}]}, "producer": PAINT}


def test_别人接的插件工具_我写不进能力(tmp_path) -> None:
    """工具在不在按**开卡的人**算:他没有这个插件的连接,开卡时就说清楚是哪个插件。"""
    owner = fresh_client()
    ws = _workspace(owner)
    _install_plugin(tmp_path)
    mate = second_client("mate")
    _connect(_me(mate), name="mate 的工具箱")
    board_id = _board(owner, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hi"}])

    refused = _edit(owner, ws, board_id, [{"kind": "set_form", "item_id": "n1", "producer": SHOUT}])
    assert refused.status_code == 422, refused.text
    assert "画板工具箱" in refused.json()["detail"]

    _connect(_me(owner))
    assert _edit(owner, ws, board_id, [{"kind": "set_form", "item_id": "n1", "producer": SHOUT}]).status_code == 200


def test_画板表单上看不见的字段_智能体也写不进去(tmp_path) -> None:
    """参数规矩对智能体也一样:原始 JSON 这类字段在画板的表单上不出现,替人写进去就是一份面板打开也看不见、
    改不了的配置。不是内容变换的插件工具(列清单)也写不进去,说清楚它归工作流。"""
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hi"}])

    hidden = _edit(client, ws, board_id, [{"kind": "add_item", "type": "image", "item_id": "i1", "producer": PAINT,
                                           "config": {"prompt": "猫", "extra": {"a": 1}}}])
    assert hidden.status_code == 422, hidden.text
    assert "extra" in hidden.json()["detail"]

    listing = _edit(client, ws, board_id, [{"kind": "set_form", "item_id": "n1",
                                            "producer": "node:plugin.dev.test.boardtools.listing"}])
    assert listing.status_code == 422, listing.text
    assert "Listing" in listing.json()["detail"] and "工作流" in listing.json()["detail"], "说的是工具的名字"

    assert _edit(client, ws, board_id, [{"kind": "add_item", "type": "image", "item_id": "i1", "producer": PAINT,
                                         "config": {"prompt": "猫"}}]).status_code == 200


def test_一格上别的能力的插件卸了_不拦这一次写的东西(tmp_path) -> None:
    """只查这一次写了的那几份:便签上存着另一个插件的能力设置(那个插件此刻不在),照样能写翻译的设置。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hi", "form": {
        "abilities": {"node:plugin.gone.tool": {"config": {"x": 1}}}, "producer": "write"}}])
    card = _edit(client, ws, board_id, [{"kind": "set_form", "item_id": "n1", "producer": TRANSLATE,
                                         "config": {"target_lang": "en"}}])
    assert card.status_code == 200, card.text


# ── list_board_producers ────────────────────────────────────────────────────


def _route_mcp_to(client, monkeypatch) -> None:
    """工具体经回环 HTTP 回连后端;TestClient 没有真实端口,把 _get/_post 路由回它本身。"""

    def fake_get(path: str, params: dict | None = None, **_kwargs) -> object:
        res = client.get(path, params=params)
        assert res.status_code < 300, res.text
        return res.json()

    def fake_post(path: str, payload: dict, **_kwargs) -> object:
        res = client.post(path, json=payload)
        if res.status_code >= 300:
            raise ValueError(f"{res.status_code}: {res.json().get('detail')}")
        return res.json()

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    monkeypatch.setattr(mcp_server, "_post", fake_post)


def test_list_board_producers_只列这个人自己接的工具(tmp_path, monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _install_plugin(tmp_path, "dev.test.othertools")
    _connect(_me(client))
    mate = second_client("mate")
    _connect(_me(mate), "dev.test.othertools", name="别人的")
    _route_mcp_to(client, monkeypatch)

    res = client.post("/api/agent/tools/list_board_producers", json={"arguments": {"workspace_id": ws}})
    assert res.status_code == 200, res.text
    listed = {one["id"]: one for one in res.json()["result"]}
    #: 和界面拿到的是同一份(同一个接口),只是只留能照存下的表单替人跑的那些。
    panel = {one["id"]: one for one in client.get("/api/boards/producers", params={"workspace_id": ws}).json()}
    assert all(listed[one] == panel[one] for one in listed)
    assert SHOUT in listed and TRANSLATE in listed
    assert not any(one.startswith("node:plugin.dev.test.othertools.") for one in listed), "列出了别人的连接"
    assert not {"generate", "write", "speak", "trim"} & set(listed), "内置的生成、写字、配音由用户在面板上发起"
    #: 3D 场景格上的渲白模也在:它的表单就是运行那一份,智能体能写、能替人点运行。
    assert listed["scene_render"]["hosts"] == ["scene"] and "node:scene_render" not in listed
    assert listed[SHOUT]["effects"] == "none" and listed[PAINT]["effects"] == "external"
    #: 每一项说清楚挂在哪、是能力还是填法、宿主的内容填进哪个字段。
    assert listed[TRANSLATE]["role"] == "ability" and listed[TRANSLATE]["hosts"] == ["note", "document"]
    assert listed[TRANSLATE]["host_fields"] == {"note": "text", "document": "text"}
    assert listed[PAINT]["role"] == "slot" and listed[PAINT]["hosts"] == ["image"]
    assert listed[TRANSLATE]["config"]["text"]["board_sources"] == ["note", "document"]


# ── run_board_item ──────────────────────────────────────────────────────────


def test_只读的能力直接跑_卡留痕不等人(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [{"id": "a1", "kind": "note", "x": 0, "y": 0, "text": "hello"}])

    #: 调用方在 payload 里自称「只读」不算数 —— 由开卡时的干跑写回。
    card = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "a1", "producer": SHOUT,
                                                "effects": "external"})
    assert card.status_code == 200, card.text
    assert card.json()["permission"] == "edit"
    assert card.json()["payload"]["ability"] is True
    done = _settle_card(client, card.json()["id"])
    assert done["status"] == "executed", done.get("error")
    assert done["decision_mode"] == "no-card"
    assert done["result"]["item_id"] == "a1" and done["result"]["job_id"] and done["result"]["producer"] == SHOUT

    canvas = _settled(client, board_id, ws)
    [made] = _derived(canvas)
    assert made["text"] == "HELLO"


def test_对外的生成器要等人批准_用批准者自己的连接(tmp_path) -> None:
    """共享画板上空格子的生成器存着主人选的连接;mate 让智能体跑它,卡上说的、真跑时用的都是 mate 自己的连接。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginInvocation

    owner = fresh_client()
    ws = _workspace(owner)
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    _install_plugin(tmp_path)
    mine = _connect(_me(owner))
    board_id = _board(owner, ws, [{"id": "a1", "kind": "image", "x": 0, "y": 0, "form": {
        "config": {"instance_id": mine, "prompt": "猫"}, "bindings": {}, "producer": PAINT}}])

    #: mate 还没接这个插件:开卡时就拒,说清楚是哪个插件。
    refused = _card(mate, ws, "run_board_item", {"board_id": board_id, "item_id": "a1"})
    assert refused.status_code == 422 and "画板工具箱" in refused.json()["detail"]

    theirs = _connect(_me(mate), name="mate 的工具箱")
    card = _card(mate, ws, "run_board_item", {"board_id": board_id, "item_id": "a1", "effects": "none"})
    assert card.status_code == 200, card.text
    assert card.json()["payload"]["ability"] is False
    pending = _settle_card(mate, card.json()["id"])
    assert pending["status"] == "pending", "对外的工具没等人就跑了"
    assert pending["permission"] == "external"
    assert "mate 的工具箱" in pending["summary"] and "B" in pending["summary"]
    assert "run" not in _items(owner, ws, board_id)["a1"], "卡还没批,那一格就进了「在跑」"

    done = mate.post(f"/api/confirmations/{card.json()['id']}/approve").json()
    assert done["status"] == "executed", done.get("error")
    canvas = _settled(owner, board_id, ws)
    slot = next(one for one in canvas["items"] if one["id"] == "a1")
    assert slot["run"]["status"] == "succeeded" and slot.get("asset_id"), "那张图填进这一格"
    assert [one["kind"] for one in _derived(canvas)] == ["note"]
    with SessionLocal() as db:
        used = {row.instance_id for row in db.query(PluginInvocation).filter(PluginInvocation.tool_name == "paint")}
    assert used == {theirs}, "替 mate 跑的用了主人的连接"
    #: 表单原样留着主人选的那条。
    assert _items(owner, ws, board_id)["a1"]["form"]["config"]["instance_id"] == mine


def test_拒了就什么都不跑(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [{"id": "a1", "kind": "image", "x": 0, "y": 0, "form": {
        "config": {"prompt": "猫"}, "bindings": {}, "producer": PAINT}}])

    card = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "a1"})
    assert card.status_code == 200, card.text
    rejected = client.post(f"/api/confirmations/{card.json()['id']}/reject").json()
    assert rejected["status"] == "rejected"
    items = _items(client, ws, board_id)
    assert "run" not in items["a1"] and list(items) == ["a1"]


def test_批准之前那一格换了生成器_就不跑(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [{"id": "a1", "kind": "image", "x": 0, "y": 0, "form": {
        "config": {"prompt": "猫"}, "bindings": {}, "producer": PAINT}}])
    card = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "a1"})
    assert card.status_code == 200, card.text

    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    board["canvas"]["items"][0]["form"] = {"config": {}, "bindings": {}, "producer": MANY}
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board["revision"], "canvas": board["canvas"]})
    assert saved.status_code == 200, saved.text

    done = client.post(f"/api/confirmations/{card.json()['id']}/approve").json()
    assert done["status"] == "failed" and "a1" in done["error"]
    assert "run" not in _items(client, ws, board_id)["a1"]


def test_内置产出者和填法不由智能体当能力点运行(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    from tests.util import seed_assets

    seed_assets(ws, {"a-1": "image"})
    board_id = _board(client, ws, [
        {"id": "i1", "kind": "image", "x": 0, "y": 0, "form": {"prompt": "猫", "producer": "generate"}},
        {"id": "i2", "kind": "image", "x": 0, "y": 300, "asset_id": "a-1"},
        {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": "hi"},
    ])
    #: 空槽上的内置生成:表单是面板的形状,由用户发起。
    refused = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "i1"})
    assert refused.status_code == 422, refused.text
    assert "i1" in refused.json()["detail"]
    #: 便签上的写字同理。
    refused = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "n1", "producer": "write"})
    assert refused.status_code == 422 and "n1" in refused.json()["detail"]
    #: 生成器不是一项能力:点名它跑在一张已经有图的格子上,会把产出填进去 —— 拒。
    refused = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "i2", "producer": PAINT})
    assert refused.status_code == 422 and "i2" in refused.json()["detail"]
    missing = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "ghost"})
    assert missing.status_code == 422 and "ghost" in missing.json()["detail"]


def test_花钱的按_ai_cost_开卡_对外的按_external() -> None:
    """能力的后果决定卡的档位 —— 自动档里花钱的有连开上限,对外的回到人(见 autopilot)。"""
    from app.domain.agent.confirmable import tool_spec

    spec = tool_spec("run_board_item")
    assert spec is not None and spec.permission == "edit" and spec.needs_card is not None
    assert [spec.escalate(None, "run_board_item", {"effects": one}) for one in ("none", "paid", "external")] == [
        None, "ai-cost", "external"]
    assert [spec.needs_card(None, {"effects": one}) for one in ("none", "paid", "external")] == [False, True, True]
    #: 没写回事实的 payload(不该发生)按要问人算。
    assert spec.needs_card(None, {}) is True


def test_智能体经工具入口跑一格的能力_拿到的是执行结果(tmp_path, monkeypatch) -> None:
    """sidecar 那条路:run_board_item 是确认门控工具,调用只拿到卡;卡已经被判「不用问人」执行掉了。"""
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _board(client, ws, [{"id": "a1", "kind": "note", "x": 0, "y": 0, "text": "hi"}])
    _route_mcp_to(client, monkeypatch)

    manifest = {one["name"]: one for one in client.get("/api/agent/tools").json()}
    assert manifest["run_board_item"]["confirmation"] is True
    assert manifest["list_board_producers"]["read_only"] is True

    res = client.post("/api/agent/tools/run_board_item", json={
        "arguments": {"board_id": board_id, "item_id": "a1", "producer": SHOUT, "workspace_id": ws},
        "requested_by": "pi-agent"})
    assert res.status_code == 200, res.text
    card_id = res.json()["result"]["confirmation_id"]
    done = _settle_card(client, card_id)
    assert done["status"] == "executed" and done["requested_by"] == "pi-agent"
    [made] = _derived(_settled(client, board_id, ws))
    assert made["text"] == "HI"


def test_卡上说清跑哪个工具_用哪条连接_有什么后果() -> None:
    """确认卡是授权界面:点「批准」之前唯一会读的就是这一行。内置节点的名字是 i18n key,按读的人的语言翻。"""
    import re

    from app.core.i18n import render_message
    from app.domain.agent.confirmable import tool_spec

    spec = tool_spec("run_board_item")
    external = {"producer": "node:translate", "effects": "external", "tool": {"key": "wfNode_translate"},
                "board_name": "Storyboard", "item_title": "", "connection": ""}
    key, params = spec.summarize(None, external)
    zh, en = render_message(key, "zh", params), render_message(key, "en", params)
    assert "翻译" in zh and "Storyboard" in zh and "撤不回" in zh
    assert "Translate" in en and "cannot be undone" in en
    assert not re.search(r"[一-鿿]", en), f"英文卡里还有中文:{en}"

    plugin = {"producer": PAINT, "effects": "paid", "tool": {"text": "Paint"}, "board_name": "B",
              "item_title": "主视觉", "connection": "我的工具箱"}
    key, params = spec.summarize(None, plugin)
    zh = render_message(key, "zh", params)
    assert "Paint" in zh and "主视觉" in zh and "我的工具箱" in zh and "费用" in zh
