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
        ({"items": [{"id": "a", "kind": "image", "x": 0, "y": 0}]}, "图片项没有素材"),
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
