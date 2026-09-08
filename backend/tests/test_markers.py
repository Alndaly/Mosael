"""画布标记(位置书签)。

钉两件事:标记**不是节点**(所以两个页面各存各的列表,规则却只有一份),以及
**同一份文档里一个快捷键只能绑一个标记** —— 绑重了存得下,但按下去只会跳到其中一个,
另一个从此再也跳不到,而用户看到的是"这个快捷键坏了"。
"""

import pytest

from tests.util import fresh_client


def test_shortcuts_are_canonicalized_so_duplicates_are_detectable():
    """`Shift+Mod+k` 和 `Mod+Shift+K` 是同一个绑定。不归一的话查重查不出来。"""
    from app.domain.markers import MarkerError, normalize_shortcut

    assert normalize_shortcut("Shift+Mod+k") == "Mod+Shift+K"
    assert normalize_shortcut("ctrl+1") == normalize_shortcut("cmd+1") == "Mod+1"
    assert normalize_shortcut("option+F5") == "Alt+F5"
    assert normalize_shortcut("m") == "M"

    for bad in ["", "Mod+", "Hyper+K", "Mod+Mod+K", "Mod+Enter", "Escape", "Mod+ArrowUp", "Space"]:
        with pytest.raises(MarkerError):
            normalize_shortcut(bad)


def test_two_markers_cannot_share_one_shortcut():
    from app.domain.markers import MarkerError, normalize_markers

    markers = [
        {"id": "a", "name": "开头", "x": 0, "y": 0, "shortcut": "Mod+1"},
        {"id": "b", "name": "结尾", "x": 10, "y": 10, "shortcut": "mod+1"},
    ]
    with pytest.raises(MarkerError) as excinfo:
        normalize_markers(markers)
    # 报错要说清楚是**和谁**撞了 —— 否则用户只知道"不行",不知道该去解绑哪一个。
    assert "开头" in str(excinfo.value)

    markers[1]["shortcut"] = "Mod+2"
    assert [one["shortcut"] for one in normalize_markers(markers)] == ["Mod+1", "Mod+2"]

    # 没绑键的标记随便几个都行:冲突的是键,不是标记。
    assert len(normalize_markers([{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 1, "y": 1}])) == 2


def test_board_canvas_keeps_markers_beside_items():
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "标记"}).json()["id"]
    canvas = {
        "items": [{"id": "note-1", "kind": "note", "x": 0, "y": 0}],
        "edges": [],
        "markers": [{"id": "m1", "name": "分镜起点", "x": 320, "y": -40, "shortcut": "alt+1"}],
    }
    board = c.post("/api/boards", json={"workspace_id": ws, "name": "板", "canvas": canvas}).json()
    assert board["canvas"]["markers"] == [
        {"id": "m1", "name": "分镜起点", "x": 320.0, "y": -40.0, "shortcut": "Alt+1"}
    ]
    # 标记没有混进 items:每一处遍历 items 的地方都不必先分辨"这个是不是标记"。
    assert [one["id"] for one in board["canvas"]["items"]] == ["note-1"]

    # 老画板(存的时候还没有 markers 这个键)读回来是空列表,而不是缺一个键。
    plain = c.post("/api/boards", json={"workspace_id": ws, "name": "老板"}).json()
    assert plain["canvas"]["markers"] == []

    bad = {**canvas, "markers": [dict(canvas["markers"][0], id="m2")]}
    bad["markers"].append({"id": "m3", "x": 0, "y": 0, "shortcut": "Alt+1"})
    r = c.post("/api/boards", json={"workspace_id": ws, "name": "撞键", "canvas": bad})
    assert r.status_code == 400, r.text


def test_workflow_graph_carries_markers_without_them_becoming_nodes():
    """标记不进 nodes —— 进了就要有节点类型,而运行时会在「未知节点类型」上失败。"""
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "标记"}).json()["id"]
    graph = {
        "nodes": [{"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}}],
        "edges": [],
        "markers": [{"id": "m1", "name": "这一段", "x": 640, "y": 120, "shortcut": "Mod+Alt+2"}],
    }
    wf = c.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": graph}).json()
    assert wf["graph"]["markers"][0]["shortcut"] == "Mod+Alt+2"
    assert [node["id"] for node in wf["graph"]["nodes"]] == ["start"]

    graph["markers"].append({"id": "m2", "x": 0, "y": 0, "shortcut": "mod+alt+2"})
    r = c.patch(f"/api/workflows/{wf['id']}", json={"graph": graph})
    assert r.status_code == 422, r.text
    assert "Mod+Alt+2" in r.text
