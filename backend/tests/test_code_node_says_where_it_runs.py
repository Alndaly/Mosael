"""代码节点的说明写的是它实际跑在哪里。

说明此前写「与插件同级的本地信任沙箱」—— 那是代码节点还在本机子进程里跑时的话;隔离早已搬到
domain/sandbox(无网络的 Docker 容器),执行器里却还留着那一套子进程的包装和环境(没人调用)。
读说明的人会以为代码能联网、能读本机文件,或者以为它和插件一样被信任。
"""

from __future__ import annotations

import inspect

from app.core.i18n import t
from app.domain import sandbox
from app.domain.workflows.executors import basic


def test_说明说的是_Docker_容器_没有网络() -> None:
    zh, en = t("wfNode_code_desc", "zh"), t("wfNode_code_desc", "en")
    assert "Docker" in zh and "没有网络" in zh and "信任" not in zh
    assert "Docker" in en and "no network" in en and "trusted" not in en
    # 说明对得上实现:沙箱确实断网。
    assert '"--network=none"' in inspect.getsource(sandbox)


def test_执行器里不再留着本机子进程那一套() -> None:
    for name in ("_CODE_WRAPPER", "_code_node_env", "CODE_OUTPUT_CAP"):
        assert not hasattr(basic, name), name


def test_智能体加代码节点的卡_说的是隔离的_Docker_容器_不是本地() -> None:
    """改图卡上那句警示是用户点批准前唯一会读的后果说明。它此前写「运行时执行本地 Python」——
    读的人以为批了就是在自己电脑上不隔离地跑代码,而实际跑在断网的 Docker 容器里。"""
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()["id"]
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "edit_workflow", "requested_by": "pi",
        "payload": {"workflow_id": wf, "operations": [
            {"kind": "add_node", "type": "code", "node_id": "c1", "config": {"code": "output = 1"}}]},
    })
    assert card.status_code == 200, card.text
    zh = client.get(f"/api/confirmations/{card.json()['id']}", headers={"Accept-Language": "zh-CN"}).json()
    en = client.get(f"/api/confirmations/{card.json()['id']}", headers={"Accept-Language": "en-US"}).json()
    assert "Docker" in zh["warning"] and "没有网络" in zh["warning"] and "本地" not in zh["warning"]
    assert "Docker" in en["warning"] and "no network" in en["warning"] and "local Python" not in en["warning"]
