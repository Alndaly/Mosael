"""卡上的失败原因整句存下,不按位置截成半句。

此前 approve_confirmation 存的是 `str(exc)[:500]`:长一点的原因(工作流运行前检查把每个节点的问题拼在一起、
供应商的原话)被切在第 500 个字上 —— 切掉的恰好是后半截,而原因往往就写在后半截。用户在卡上、智能体经
get_confirmation 读到的都是那半句。长短是界面排版的事(卡上折起来显示),不是存储的事。
"""

from __future__ import annotations

import dataclasses

from app.domain.agent.confirmable import registry
from app.domain.agent.errors import ConfirmationError
from tests.util import fresh_client


def test_长原因整句落在卡上(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()["id"]
    reason = "；".join(f"节点 n{index} 缺少必填项「提示词」" for index in range(40)) + "。最后这一句才说怎么修:去节点里填上。"
    assert len(reason) > 500

    def boom(db, confirmation, actor):
        raise ConfirmationError(reason)

    #: 执行体换成一个照实抛长原因的;**批准、回滚、记失败**走的都是真的那一条(路由 → authorize_and_approve)。
    spec = registry._TOOLS["run_workflow"]
    monkeypatch.setitem(registry._TOOLS, "run_workflow", dataclasses.replace(spec, execute=boom))
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi", "payload": {"workflow_id": wf, "params": {}},
    }).json()

    settled = client.post(f"/api/confirmations/{card['id']}/approve").json()

    assert settled["status"] == "failed"
    assert settled["error"] == reason
    assert client.get(f"/api/confirmations/{card['id']}").json()["error"].endswith("去节点里填上。")
