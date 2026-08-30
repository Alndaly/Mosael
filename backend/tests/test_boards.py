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
    job = SimpleNamespace(id="job-x", status="succeeded", result={"asset_ids": ["asset-42"]})
    deliver_generated(db, job, receipt_to_item(board_id, item_id))
    item = (db.get(Board, board_id).canvas["items"])[0]
    db.close()

    assert item["asset_id"] == "asset-42"
    assert "job_id" not in item, "填完素材还留着 job_id,界面会一直显示在生成"


def test_任务失败时留着这一项并写上原因() -> None:
    """失败是这一项的一种**状态**,不是删掉它的理由。

    三种写法里只有一种是对的:留着 job_id(画布永远转圈,用户以为还在跑)、整项删掉
    (框凭空消失,连同刚写的提示词 —— 而他要做的下一件事十有八九是"改个字再来一次")、
    或者摘掉 job_id、留下这一项和原因。这里钉的是第三种。"""
    from types import SimpleNamespace

    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id, item_id = _pending_board(client, ws)

    from app.core.db import SessionLocal

    db = SessionLocal()
    job = SimpleNamespace(id="job-x", status="failed", result=None, error="供应商说这个提示词不行")
    deliver_generated(db, job, receipt_to_item(board_id, item_id))
    items = db.get(Board, board_id).canvas["items"]
    db.close()

    assert [one["id"] for one in items] == [item_id], "失败了却把这一项从画布上删了"
    failed = items[0]
    assert "job_id" not in failed, "任务已经结束了,job_id 还留着 —— 画布会一直转圈"
    assert failed["error"] == "供应商说这个提示词不行"


def test_任务失败但没留下原因时不写空() -> None:
    """空的 error 会被 normalize 丢掉,于是那一项看起来又像个没开始的空槽。"""
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.db.models import Board
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id, item_id = _pending_board(client, ws)

    db = SessionLocal()
    deliver_generated(db, SimpleNamespace(id="job-x", status="failed", result=None, error=""), receipt_to_item(board_id, item_id))
    items = db.get(Board, board_id).canvas["items"]
    db.close()

    assert items[0]["error"] == "failed"


def test_跑挂了也留着连进来的那条线() -> None:
    """上游那张参考图还连着,重来一次才不用重新连 —— 而这正是失败之后最常做的事。"""
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
    deliver_generated(db, SimpleNamespace(id="job-x", status="failed", result=None, error="炸了"), receipt_to_item(board_id, "gen-1"))
    board = db.get(Board, board_id)
    items, edges = board.canvas["items"], board.canvas["edges"]
    db.close()

    assert [item["id"] for item in items] == ["note-1", "gen-1"]
    assert [edge["id"] for edge in edges] == ["e1"]


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
        db, SimpleNamespace(id="job-x", status="succeeded", result={"asset_ids": ["asset-9"]}), receipt_to_item(board_id, item_id)
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


def test_一次出多张时每一张都落回画布() -> None:
    """选了 4 张就该看见 4 张。

    图像接口的 `n` 选几就回几张,而回执此前只填第一张 —— 用户按 4 张付了钱,画布上只多出
    一张。另外三张确实在素材库里,只是他不知道,也没有任何地方会报错。
    """
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {
                "items": [{"id": "img-1", "kind": "image", "x": 100, "y": 50, "width": 200, "job_id": "job-x"}],
                "edges": [],
            },
        },
    ).json()["id"]

    db = SessionLocal()
    deliver_generated(
        db,
        SimpleNamespace(id="job-x", status="succeeded", result={"asset_ids": ["a", "b", "c"]}),
        receipt_to_item(board_id, "img-1"),
    )
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    db.close()

    assert [one["asset_id"] for one in items] == ["a", "b", "c"], f"只落回了一部分:{items}"
    assert all("job_id" not in one for one in items), "还留着转圈的占位"
    # 挨着原处往右排,别叠在一起 —— 叠住的话看起来就还是只出了一张。
    assert [one["x"] for one in items] == [100, 324, 548]
    assert {one["y"] for one in items} == {50}


def test_分组框记得住联动拖动这件事() -> None:
    """「这一组是一个整体」是这个框的**性质**,不是一次操作的临时状态 —— 重进画板还该是那样。"""
    canvas = normalize_canvas(
        {"items": [{"id": "f", "kind": "frame", "x": 0, "y": 0, "move_children": True}], "edges": []}
    )
    assert canvas["items"][0]["move_children"] is True

    # 别的类型给了就是写错了 —— 悄悄丢掉的话,前端读回来会以为自己没存上。
    with pytest.raises(BoardDomainError):
        normalize_canvas(
            {"items": [{"id": "n", "kind": "note", "x": 0, "y": 0, "move_children": True}], "edges": []}
        )
    with pytest.raises(BoardDomainError):
        normalize_canvas(
            {"items": [{"id": "f", "kind": "frame", "x": 0, "y": 0, "move_children": "yes"}], "edges": []}
        )


def test_写文案就地落进那张便签_不新建() -> None:
    """AI 写完的字要放进用户摆好的那张便签里 —— 位置、颜色、大小都归他。"""
    from app.core.db import SessionLocal
    from app.domain.boards import write_text

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {
                "items": [{"id": "n1", "kind": "note", "x": 40, "y": 80, "width": 220, "color": "green"}],
                "edges": [],
            },
        },
    ).json()["id"]

    db = SessionLocal()
    board = write_text(db, workspace_id=ws, board_id=board_id, item_id="n1", text="城市夜景下的一只白猫")
    items = board.canvas["items"]
    assert len(items) == 1, "写字居然新建了一项"
    assert items[0]["text"] == "城市夜景下的一只白猫"
    assert (items[0]["x"], items[0]["y"], items[0]["color"]) == (40, 80, "green"), "把用户摆好的东西改了"

    with pytest.raises(BoardDomainError):
        write_text(db, workspace_id=ws, board_id=board_id, item_id="没这项", text="x")
    db.close()


def test_写文案没配模型时给准信而不是五百() -> None:
    """一个连接都没有时,用户该看到「先去设置里配一个」,不是一页 traceback。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={"workspace_id": ws, "name": "B", "canvas": {"items": [{"id": "n1", "kind": "note", "x": 0, "y": 0}], "edges": []}},
    ).json()["id"]

    answer = client.post(
        f"/api/boards/{board_id}/write",
        json={"workspace_id": ws, "item_id": "n1", "prompt": "写一句广告词"},
    )
    assert answer.status_code == 422, answer.text
    assert "供应商" in answer.json()["detail"]

    # 空要求也别发出去 —— 供应商那边回的是一句看不懂的英文 400。
    empty = client.post(
        f"/api/boards/{board_id}/write",
        json={"workspace_id": ws, "item_id": "n1", "prompt": "   "},
    )
    assert empty.status_code == 400


def test_便签上已有内容时是改写而不是重写() -> None:
    """有字就该把现有内容单独交代给模型,并说明用户给的是**改法**。

    揉成一段发过去的话,模型会把「改短一点」当成正文的一部分写进便签;什么都不说的话,
    它会把整篇重写一遍 —— 而用户只想动其中一句。两种都不报错,只是结果不对。
    """
    from unittest.mock import patch as mock_patch

    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from app.domain import provider_models

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {
                "items": [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "原来的那句话"}],
                "edges": [],
            },
        },
    ).json()["id"]

    #: 真建一条连接 —— 计量事件带着 provider_profile_id 的外键,拿个假对象顶上会在落账时炸。
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "openai", "name": "演示", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    #: 密钥是按人存的,建连接时那个字段不落钥匙 —— 得再存一次(见 provider_credentials)。
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "gpt-4.1-mini", source="manual")
        db.commit()

    seen: dict = {}

    def fake_chat(target, messages, **kwargs):
        seen["messages"] = messages
        return "改过之后的那句话"

    with mock_patch("app.domain.ai_chat.chat", side_effect=fake_chat):
        answer = client.post(
            f"/api/boards/{board_id}/write",
            json={"workspace_id": ws, "item_id": "n1", "prompt": "改短一半"},
        )

    assert answer.status_code == 200, answer.text
    messages = seen["messages"]
    assert "改法" in messages[0]["content"], "没告诉模型这是改写"
    # 现有内容自成一轮 —— 和要求分开。
    assert any("原来的那句话" in one["content"] and "改短一半" not in one["content"] for one in messages[1:]), messages
    assert messages[-1]["content"] == "改短一半"
    assert answer.json()["canvas"]["items"][0]["text"] == "改过之后的那句话"


def test_连过来的图片会让模型看着写() -> None:
    """图片连到便签,意思是「照着这张图写」—— 不把图带上的话,模型只能凭提示词瞎编。

    **只收图片**:视频和音频这条路吃不下(要抽帧、要转写,那是 analyze_asset 的事),
    悄悄发过去只会换回一句看不懂的报错。
    """
    from unittest.mock import patch as mock_patch

    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from app.domain import provider_models

    client = fresh_client()
    ws = _workspace(client)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    image_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("一张图.png", png, "image/png")}
    ).json()["id"]

    board_id = client.post(
        "/api/boards",
        json={"workspace_id": ws, "name": "B", "canvas": {"items": [{"id": "n1", "kind": "note", "x": 0, "y": 0}], "edges": []}},
    ).json()["id"]
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "openai", "name": "演示", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "gpt-4.1-mini", source="manual")
        db.commit()

    seen: dict = {}

    with mock_patch("app.domain.ai_chat.chat", side_effect=lambda t, m, **k: seen.setdefault("m", m) and "" or "写好了"):
        answer = client.post(
            f"/api/boards/{board_id}/write",
            json={"workspace_id": ws, "item_id": "n1", "prompt": "照这张图写一句", "source_assets": [image_id]},
        )

    assert answer.status_code == 200, answer.text
    last = seen["m"][-1]["content"]
    assert isinstance(last, list), f"图没带上,发过去的还是纯文本:{last!r}"
    assert last[0] == {"type": "text", "text": "照这张图写一句"}
    assert last[1]["type"] == "image_url" and last[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_视频给画面_音频给转写_都不做多余的模型调用() -> None:
    """三种素材三条路,而它们本来就不一样:

     · 图片直接是一帧画面;
     · 视频**在这一次调用里抽帧** —— 先跑一遍 analyze_asset 再把结论喂进来的话,要多花
       一次模型调用和几秒钟,而模型本来就能直接看这几帧;
     · 音频没有画面,能给的是转写;没转写过就跳过,不在这里顺手起一个 ASR 任务
       (一次「写句文案」会变成一次要等的后台作业)。
    """
    from unittest.mock import patch as mock_patch

    from app.api.routes.boards import _look_at
    from app.core.db import SessionLocal

    client = fresh_client()
    ws = _workspace(client)
    video_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("片子.mp4", b"fake mp4", "video/mp4")}
    ).json()["id"]
    audio_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("声音.mp3", b"fake mp3", "audio/mpeg")}
    ).json()["id"]

    with SessionLocal() as db:
        with mock_patch(
            "app.domain.analysis.service.extract_video_frames", return_value=[b"frame-1", b"frame-2"]
        ):
            parts, materials = _look_at(db, ws, [video_id])
        assert [one["type"] for one in parts] == ["image_url", "image_url"], "视频没抽成画面"
        assert materials == []

        # 没转写过的音频:跳过,不报错、也不顺手起任务。
        with mock_patch("app.domain.analysis.service._asset_transcript_text", return_value=None):
            assert _look_at(db, ws, [audio_id]) == ([], [])
        with mock_patch("app.domain.analysis.service._asset_transcript_text", return_value="他说了这些"):
            parts, materials = _look_at(db, ws, [audio_id])
        assert parts == []
        assert materials and "他说了这些" in materials[0]

        # 抽帧失败不该让整次「写文案」失败 —— 少一段素材,总比一句都写不出来好。
        from app.domain.analysis.service import AnalysisError

        with mock_patch("app.domain.analysis.service.extract_video_frames", side_effect=AnalysisError("没画面")):
            assert _look_at(db, ws, [video_id]) == ([], [])


def test_够不着的素材一律跳过() -> None:
    """不存在的、别的工作区的 —— 一律当作没有,而不是报错让整次写作失败。"""
    from app.api.routes.boards import _look_at
    from app.core.db import SessionLocal

    client = fresh_client()
    ws = _workspace(client)
    audio_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("声音.mp3", b"not really audio", "audio/mpeg")}
    ).json()["id"]

    with SessionLocal() as db:
        assert _look_at(db, ws, ["根本不存在"]) == ([], [])
        # 跨工作区的也不给。
        other = client.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
        assert _look_at(db, other, [audio_id]) == ([], [])


def test_上游便签给的材料和要求分开发() -> None:
    """揉成一段的话,模型分不清哪句是素材、哪句是指令 —— 常见的结果是把材料原样抄一遍。"""
    from unittest.mock import patch as mock_patch

    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from app.domain import provider_models

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={"workspace_id": ws, "name": "B", "canvas": {"items": [{"id": "n1", "kind": "note", "x": 0, "y": 0}], "edges": []}},
    ).json()["id"]
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "openai", "name": "演示", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "gpt-4.1-mini", source="manual")
        db.commit()

    seen: dict = {}
    with mock_patch("app.domain.ai_chat.chat", side_effect=lambda t, m, **k: seen.setdefault("m", m) and "" or "好"):
        answer = client.post(
            f"/api/boards/{board_id}/write",
            json={
                "workspace_id": ws,
                "item_id": "n1",
                "prompt": "缩成一句",
                "context": ["第一段素材", "第二段素材"],
            },
        )
    assert answer.status_code == 200, answer.text
    messages = seen["m"]
    material = next((one for one in messages if "第一段素材" in str(one["content"])), None)
    assert material is not None, "上游材料没发过去"
    assert "缩成一句" not in str(material["content"]), "材料和要求揉在了一段里"
    assert "第二段素材" in str(material["content"])
    assert messages[-1]["content"] == "缩成一句"


def test_语音合成的产出也能落回画板() -> None:
    """合成任务给的是 asset_id(单数),生成任务给的是 asset_ids(复数)。

    **这不是新旧兼容,是两种任务本来就不同。** 只认一种的话,另一种落终态时占位会被当成
    失败摘掉 —— 用户看到的是音频「生成完就没了」。
    """
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {"items": [{"id": "a1", "kind": "audio", "x": 0, "y": 0, "job_id": "job-tts"}], "edges": []},
        },
    ).json()["id"]

    db = SessionLocal()
    deliver_generated(
        db,
        SimpleNamespace(id="job-tts", status="succeeded", result={"asset_id": "snd-1", "engine": "volcano"}),
        receipt_to_item(board_id, "a1"),
    )
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    db.close()

    assert len(items) == 1, f"占位被摘掉了:{items}"
    assert items[0]["asset_id"] == "snd-1"
    assert "job_id" not in items[0]


def test_截取范围写错时当场拒绝_而不是让_ffmpeg_去发现() -> None:
    """让 ffmpeg 去发现「结束早于开始」的话,用户拿到的是一句英文报错 —— 而且是几秒之后
    从任务中心里才看到的。"""
    import pytest as _pytest

    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.domain.boards_trim import TrimError, start_trim

    client = fresh_client()
    ws = _workspace(client)
    video_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("片子.mp4", b"fake", "video/mp4")}
    ).json()["id"]
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    picture = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("一张图.png", png, "image/png")}
    ).json()["id"]

    with SessionLocal() as db:
        video = db.get(Asset, video_id)
        for start, end in ((5.0, 1.0), (2.0, 2.0), (-1.0, 3.0)):
            with _pytest.raises(TrimError):
                start_trim(db, asset=video, start=start, end=end, created_by=None)
        # 不是视听素材的也拒 —— 一张图没有时间轴,截不出「第 3 秒」。
        with _pytest.raises(TrimError):
            start_trim(db, asset=db.get(Asset, picture), start=0, end=1, created_by=None)


def test_截取产出走的是画板同一套回执() -> None:
    """截取任务给的是 asset_id(和语音合成同一个形状)—— 画板的回执两种都读得懂。"""
    from types import SimpleNamespace

    from app.core.db import SessionLocal
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post(
        "/api/boards",
        json={
            "workspace_id": ws,
            "name": "B",
            "canvas": {"items": [{"id": "v1", "kind": "video", "x": 0, "y": 0, "job_id": "job-trim"}], "edges": []},
        },
    ).json()["id"]

    db = SessionLocal()
    deliver_generated(
        db,
        SimpleNamespace(id="job-trim", status="succeeded", result={"asset_id": "cut-1"}),
        receipt_to_item(board_id, "v1"),
    )
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    db.close()
    assert items[0]["asset_id"] == "cut-1" and "job_id" not in items[0]


def test_帧条按需生成并缓存在素材旁边() -> None:
    """剪辑面板一打开就要看到整条片子的样子。**一张横向长图,不是十二个请求** —— 分成
    十二个的话它们会一格一格跳出来,每格还各过一次鉴权和落盘。

    生成是尽力而为:抽不出来就没有帧条,面板退回到只填秒数,而不是整个打不开。
    """
    from unittest.mock import patch as mock_patch

    from app.media.filmstrip import filmstrip_path
    from app.media.paths import resolve_key

    client = fresh_client()
    ws = _workspace(client)
    video_id = client.post(
        "/api/assets/import", data={"workspace_id": ws}, files={"file": ("片子.mp4", b"fake", "video/mp4")}
    ).json()["id"]

    # 抽不出来(假 mp4):404,而不是 500。
    assert client.get(f"/api/assets/{video_id}/filmstrip").status_code == 404

    from app.core.db import SessionLocal
    from app.db.models import Asset

    with SessionLocal() as db:
        directory = resolve_key(db.get(Asset, video_id).file_key).parent

    made: dict = {}

    def fake_generate(source, kind, asset_directory):
        made["count"] = made.get("count", 0) + 1
        target = filmstrip_path(asset_directory)
        target.write_bytes(b"\xff\xd8\xff\xd9")  # 一个最小的 jpeg 头尾
        return target

    with mock_patch("app.media.filmstrip.generate_filmstrip", side_effect=fake_generate):
        assert client.get(f"/api/assets/{video_id}/filmstrip").status_code == 200
        # 第二次直接读盘 —— 同一段素材会被反复打开剪辑面板,每次重跑 ffmpeg 太贵。
        assert client.get(f"/api/assets/{video_id}/filmstrip").status_code == 200
    assert made["count"] == 1, f"帧条被重复生成了 {made['count']} 次"
    assert filmstrip_path(directory).is_file()


def test_取帧要精确到那一秒_而不是最近的关键帧() -> None:
    """`-ss` 放在 `-i` **之后**才是逐帧解到那个时间点。放在前面会跳到最近的关键帧 ——
    用户在帧条上停在 3.2 秒,拿回来的是 2.8 秒那一帧,而画面看着差不多,他不会发现取错了。
    """
    from unittest.mock import patch as mock_patch

    from app.media.still import grab_frame

    seen: dict = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        pathlib_target = args[-1]
        import pathlib as _p
        _p.Path(pathlib_target).write_bytes(b"\xff\xd8\xff\xd9")
        return None

    import pathlib, tempfile

    with tempfile.TemporaryDirectory() as tmp:
        source = pathlib.Path(tmp) / "in.mp4"
        source.write_bytes(b"x")
        with mock_patch("app.media.still.run_logged", side_effect=fake_run):
            grab_frame(source, 3.2, pathlib.Path(tmp) / "out.jpg")

    args = seen["args"]
    assert args.index("-ss") > args.index("-i"), f"-ss 跑到 -i 前面了,会对齐到关键帧:{args}"
    assert args[args.index("-ss") + 1] == "3.200"
    assert "-frames:v" in args and args[args.index("-frames:v") + 1] == "1"


def test_取帧落在片尾之后要说人话() -> None:
    """ffmpeg 这时会成功退出但什么都不写 —— 一个空文件比报错更难查。"""
    import pathlib
    import tempfile
    from unittest.mock import patch as mock_patch

    import pytest as _pytest

    from app.media.still import StillError, grab_frame

    with tempfile.TemporaryDirectory() as tmp:
        source = pathlib.Path(tmp) / "in.mp4"
        source.write_bytes(b"x")
        with mock_patch("app.media.still.run_logged", return_value=None):
            with _pytest.raises(StillError, match="没有画面"):
                grab_frame(source, 999, pathlib.Path(tmp) / "out.jpg")
        with _pytest.raises(StillError, match="负数"):
            grab_frame(source, -1, pathlib.Path(tmp) / "out.jpg")
