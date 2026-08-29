"""创意画板:一张无限画布,用来攒想法。

这些用例分两半。前半是接口能不能用(建、读、改、删、跨工作区拿不到);后半是**画布校验**——
存进去的东西下一次是要渲染的,所以一个坐标是字符串、一个 kind 拼错了,都得在写入时就拒绝。
拒绝的那一刻用户还知道自己刚做了什么;放过去的话,用户几天后打开一张渲染到一半崩掉的板,
而错误藏在某一次自动保存里。
"""

from __future__ import annotations

import pytest

from app.domain.boards import BoardDomainError, normalize_canvas
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_建改读删一条龙() -> None:
    client = fresh_client()
    ws = _workspace(client)

    created = client.post("/api/boards", json={"workspace_id": ws, "name": "灵感"})
    assert created.status_code == 200, created.text
    board_id = created.json()["id"]
    assert created.json()["canvas"] == {"items": [], "edges": []}

    canvas = {
        "items": [
            {"id": "n1", "kind": "note", "x": 10, "y": 20, "text": "先想一个开头", "color": "yellow"},
            {"id": "n2", "kind": "note", "x": 300, "y": 20, "text": "再想结尾"},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "label": "然后"}],
    }
    saved = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas})
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["canvas"]["items"]) == 2

    listed = client.get("/api/boards", params={"workspace_id": ws}).json()
    assert [item["name"] for item in listed] == ["灵感"]

    assert client.delete(f"/api/boards/{board_id}", params={"workspace_id": ws}).status_code == 200
    assert client.get("/api/boards", params={"workspace_id": ws}).json() == []


def test_改名和存画布互不覆盖() -> None:
    """自动保存只发 canvas、重命名只发 name —— 各发各的那一半,另一半不能被 None 抹掉。

    少了这一条,用户改完名字继续在板上拖两下,名字就变回去了。
    """
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws, "name": "原名"}).json()["id"]

    canvas = {"items": [{"id": "a", "kind": "note", "x": 0, "y": 0, "text": "x"}], "edges": []}
    client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas})
    renamed = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "name": "新名"})

    assert renamed.json()["name"] == "新名"
    assert len(renamed.json()["canvas"]["items"]) == 1, "只改名字把画布清空了"

    again = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas})
    assert again.json()["name"] == "新名", "只存画布把名字改回去了"


def test_别的工作区的画板拿不到() -> None:
    client = fresh_client()
    mine = _workspace(client)
    theirs = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": mine, "name": "私密"}).json()["id"]

    # 拿着正确的 id、报另一个工作区 —— 必须当作不存在,而不是"你没权限"(后者等于确认它存在)。
    assert client.get(f"/api/boards/{board_id}", params={"workspace_id": theirs}).status_code == 404
    assert client.get("/api/boards", params={"workspace_id": theirs}).json() == []


def test_画板不存在是404_画布不合法是400() -> None:
    """两者对调用方意味着完全不同的下一步:一个是"别再重试了",一个是"改完再发"。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]

    missing = client.patch("/api/boards/nope", json={"workspace_id": ws, "name": "x"})
    assert missing.status_code == 404

    bad = client.patch(
        f"/api/boards/{board_id}",
        json={"workspace_id": ws, "canvas": {"items": [{"id": "a", "kind": "note", "x": "左边", "y": 0}]}},
    )
    assert bad.status_code == 400
    assert "x" in bad.json()["detail"]


def test_没名字时给个默认名() -> None:
    """新建按钮不该逼用户先想名字 —— 想法来的时候名字是最不重要的那部分。"""
    client = fresh_client()
    ws = _workspace(client)
    assert client.post("/api/boards", json={"workspace_id": ws}).json()["name"] == "新画板"


# ── 画布校验 ────────────────────────────────────────────────────────────────


def test_空画布和缺字段都读得回来() -> None:
    """宽进:新板、旧版本存的、少写的字段,都要能打开。"""
    assert normalize_canvas(None) == {"items": [], "edges": []}
    assert normalize_canvas({}) == {"items": [], "edges": []}
    got = normalize_canvas({"items": [{"id": "a", "kind": "note", "x": 1, "y": 2}]})
    assert got["items"][0] == {"id": "a", "kind": "note", "x": 1.0, "y": 2.0}


@pytest.mark.parametrize(
    ("canvas", "why"),
    [
        ({"items": [{"id": "a", "kind": "sticker", "x": 0, "y": 0}]}, "没有这种类型"),
        ({"items": [{"id": "a", "kind": "note", "y": 0}]}, "缺坐标"),
        ({"items": [{"id": "", "kind": "note", "x": 0, "y": 0}]}, "id 是空的"),
        ({"items": [{"id": "a", "kind": "note", "x": 0, "y": 0, "color": "橙"}]}, "不在色板里"),
        ({"items": [{"id": "a", "kind": "note", "x": 0, "y": 0, "width": 0}]}, "宽度为 0"),
        ({"items": [], "edges": [{"source": "a", "target": "b"}]}, "连线连到不存在的项"),
    ],
)
def test_写错的画布当场拒绝(canvas: dict, why: str) -> None:
    with pytest.raises(BoardDomainError):
        normalize_canvas(canvas)


def test_id_重复要拒绝() -> None:
    """前端按 id 索引,重了会**默默丢掉一个** —— 用户看到的是"我刚加的东西没了"。"""
    with pytest.raises(BoardDomainError, match="重复"):
        normalize_canvas(
            {"items": [{"id": "a", "kind": "note", "x": 0, "y": 0}, {"id": "a", "kind": "note", "x": 1, "y": 1}]}
        )


def test_布尔不算数字() -> None:
    """Python 里 True 是 1 的子类型 —— 不特判的话 `x: true` 会被当成坐标 1.0 存进去。"""
    with pytest.raises(BoardDomainError):
        normalize_canvas({"items": [{"id": "a", "kind": "note", "x": True, "y": 0}]})


def test_太大的画布拒绝() -> None:
    from app.domain.boards import MAX_ITEMS

    items = [{"id": f"n{i}", "kind": "note", "x": 0, "y": 0} for i in range(MAX_ITEMS + 1)]
    with pytest.raises(BoardDomainError, match="最多"):
        normalize_canvas({"items": items})


def test_图片视频项的三种状态都存得下() -> None:
    """空槽 / 生成中 / 有产出 —— 缺一不可。

    「节点本身就是生成单元」这件事**从空槽开始**:放下一个空的图片槽,底下挂提示词面板,
    写完提交才有任务。此前空槽和生成中都被当成错误拒掉了。
    """
    from app.domain.boards import ITEM_KINDS

    assert "video" in ITEM_KINDS
    empty, running, done = normalize_canvas(
        {
            "items": [
                {"id": "a", "kind": "image", "x": 0, "y": 0},
                {"id": "b", "kind": "image", "x": 0, "y": 0, "job_id": "j1"},
                {"id": "c", "kind": "video", "x": 0, "y": 0, "asset_id": "abc"},
            ]
        }
    )["items"]
    assert "asset_id" not in empty and "job_id" not in empty
    assert running["job_id"] == "j1"
    assert done["asset_id"] == "abc"


# ── 在画板上生成 ────────────────────────────────────────────────────────────


def _pending_board(client, ws: str) -> tuple[str, str]:
    """一张板 + 一项「正在生成」的占位。返回 (board_id, item_id)。"""
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {
        "items": [{"id": "gen-1", "kind": "image", "x": 0, "y": 0, "job_id": "job-x", "text": "一只猫"}],
        "edges": [],
    }
    client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas})
    return board_id, "gen-1"


def test_正在生成的项可以没有素材() -> None:
    """「还没有」和「不该有」是两件事。前者要占着位置让用户看见"这儿在生成"。"""
    got = normalize_canvas({"items": [{"id": "g", "kind": "image", "x": 0, "y": 0, "job_id": "j1"}]})
    assert got["items"][0]["job_id"] == "j1"
    assert "asset_id" not in got["items"][0]


def test_任务成功后占位就地变成素材() -> None:
    from types import SimpleNamespace

    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id, item_id = _pending_board(client, ws)

    from app.core.db import SessionLocal

    db = SessionLocal()
    job = SimpleNamespace(id="job-x", status="succeeded", result={"asset_id": "asset-42"})
    deliver_generated(db, job, receipt_to_item(board_id, item_id))
    item = (db.get(Board, board_id).canvas["items"])[0]
    db.close()

    assert item["asset_id"] == "asset-42"
    assert "job_id" not in item, "填完素材还留着 job_id,界面会一直显示在生成"


def test_任务失败时把占位摘掉() -> None:
    """只处理成功的话,失败时画布上会永远留着一个转圈的框 —— 用户分不清它是还在跑还是已经死了,
    而这两件事的下一步完全不同。"""
    from types import SimpleNamespace

    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id, item_id = _pending_board(client, ws)

    from app.core.db import SessionLocal

    db = SessionLocal()
    job = SimpleNamespace(id="job-x", status="failed", result=None)
    deliver_generated(db, job, receipt_to_item(board_id, item_id))
    items = db.get(Board, board_id).canvas["items"]
    db.close()

    assert items == [], "失败了却把占位留在画布上"


def test_摘掉占位时连着它的线也要去掉() -> None:
    """normalize 会拒绝悬空的线 —— 不一起去掉的话,回填这一步自己会炸,而炸在后台线程里。"""
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {
        "items": [
            {"id": "note-1", "kind": "note", "x": 0, "y": 0, "text": "一只猫"},
            {"id": "gen-1", "kind": "image", "x": 300, "y": 0, "job_id": "job-x"},
        ],
        "edges": [{"id": "e1", "source": "note-1", "target": "gen-1"}],
    }
    client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas})

    db = SessionLocal()
    deliver_generated(db, SimpleNamespace(id="job-x", status="failed", result=None), receipt_to_item(board_id, "gen-1"))
    board = db.get(Board, board_id)
    items, edges = board.canvas["items"], board.canvas["edges"]
    db.close()

    assert [item["id"] for item in items] == ["note-1"]
    assert edges == []


def test_回执登记在导入期() -> None:
    """登记在 lifespan 里的话,不跑 lifespan 的入口(TestClient、脚本)产出永远回不到画布。
    这个仓库为同一个形状修过一次(TTS 配置来源),不该再来一遍。"""
    import app.main  # noqa: F401 —— 组装根,import 它就等于装配完成

    from app.domain.boards import RECEIPT_KIND, deliver_generated
    from app.domain.jobs import _RECEIPT_DELIVERERS

    assert _RECEIPT_DELIVERERS.get(RECEIPT_KIND) is deliver_generated


def test_客户端不会覆盖它还不知道的产出() -> None:
    """必然的竞态,不是偶发:画板自动保存,而生成是异步的。

      t1 客户端存了带占位的画布 → t2 任务跑完,回执填进 asset_id
      → t3 用户又拖了一下,客户端把**它手上那份**(还是占位)存回来。

    不管的话产出就这么没了,而且不报错 —— 那一项看着还在转圈,可任务早就结束了。
    """
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id, item_id = _pending_board(client, ws)
    stale = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]

    db = SessionLocal()
    deliver_generated(
        db, SimpleNamespace(id="job-x", status="succeeded", result={"asset_id": "asset-9"}), receipt_to_item(board_id, item_id)
    )
    db.close()

    # 客户端把 t1 那份原样存回来 —— 它手上还是占位。
    got = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": stale}).json()
    item = got["canvas"]["items"][0]

    assert item["asset_id"] == "asset-9", "客户端那份把已经到达的产出覆盖掉了"
    assert "job_id" not in item


def test_音频项和图片视频同一套三状态() -> None:
    """配音、旁白、BGM 都是想法的一部分 —— 画板上摊开的东西不该只有能看的。"""
    from app.domain.boards import ITEM_KINDS

    assert "audio" in ITEM_KINDS
    empty, done = normalize_canvas(
        {
            "items": [
                {"id": "a", "kind": "audio", "x": 0, "y": 0},
                {"id": "b", "kind": "audio", "x": 0, "y": 0, "asset_id": "snd"},
            ]
        }
    )["items"]
    assert "asset_id" not in empty
    assert done["asset_id"] == "snd"


def test_在已有的空槽上生成不会撞上自己() -> None:
    """在画布上**已经存在**的那一格里点生成 —— 占位要就地更新,不是再追加一份。

    画板上的生成有两个入口:工具条上「放一个空槽去生成」是新建一项,而在已有的空槽里
    写完提示词点生成,那一项早就在画布上了。追加的话会撞上同 id 的自己(normalize_canvas
    拒重复 id),用户看到的是一句「画板项 id 重复」,而他只是点了生成。
    """
    from app.core.db import SessionLocal
    from app.domain.boards import place_pending

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {
                "items": [{"id": "img-1", "kind": "image", "x": 120, "y": 80, "width": 300, "height": 200}],
                "edges": [],
            },
        },
    ).json()["id"]

    db = SessionLocal()
    updated = place_pending(
        db,
        workspace_id=ws,
        board_id=board_id,
        # 路由拿不到用户把节点拖到了哪儿,发过来的是默认坐标 —— 不能拿它覆盖。
        item={"id": "img-1", "kind": "image", "x": 0, "y": 0, "job_id": "job-1", "text": "一个女孩"},
    )

    items = updated.canvas["items"]
    assert len(items) == 1, f"占位被追加成了第二份:{items}"
    assert items[0]["job_id"] == "job-1"
    assert items[0]["text"] == "一个女孩"
    assert (items[0]["x"], items[0]["y"]) == (120, 80), "节点自己跳回了左上角"
    assert (items[0]["width"], items[0]["height"]) == (300, 200), "用户拉过的大小被抹掉了"

    db.close()
