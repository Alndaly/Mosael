"""挪一个标记不是一次「执行版本」。

修订的不变量(见 domain/workflows/revisions):执行语义相同不增版 —— 画布布局可以保存,但不该
制造新的可执行版本。节点的坐标早就被剥掉了;**标记**(位置书签,见 domain/markers)同样是纯布局:
不执行、不连线、不产出。可它此前算进了版本身份,于是在画布上拖一下标记、改个名字、绑个快捷键,
各增一版 —— 版本历史的窗口只有 100 条,真正改了执行内容的那几版被一串"挪了个书签"挤出视野。
"""

from __future__ import annotations

import copy

from tests.util import fresh_client

RATCHET = True


def test_标记的增删改挪都不增版() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "标记", "graph": graph}).json()
    revision = workflow["revision"]
    base = workflow["graph_hash"]

    steps = []
    marked = copy.deepcopy(graph)
    marked["markers"] = [{"id": "m1", "name": "开头", "x": 10, "y": 20}]
    steps.append(marked)
    moved = copy.deepcopy(marked)
    moved["markers"][0].update(x=400, y=300, name="改名", shortcut="1")
    steps.append(moved)
    steps.append(copy.deepcopy(graph))  # 删掉

    for step in steps:
        saved = client.patch(f"/api/workflows/{workflow['id']}", json={"graph": step, "base_graph_hash": base})
        assert saved.status_code == 200, saved.text
        assert saved.json()["graph"].get("markers", []) == step.get("markers", []), "标记本身要存下来"
        assert saved.json()["revision"] == revision, "只动了标记,却多出一个执行版本"
        base = saved.json()["graph_hash"]

    # 真改了执行内容,照样增版。
    changed = copy.deepcopy(graph)
    changed["nodes"][0]["config"] = {"params": {"topic": "猫"}}
    changed_saved = client.patch(f"/api/workflows/{workflow['id']}", json={"graph": changed, "base_graph_hash": base})
    assert changed_saved.json()["revision"] == revision + 1

    # 当前投影和最新修订仍然一致:能照常运行。
    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
