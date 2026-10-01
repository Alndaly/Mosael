"""运行时传进来的空参数不盖开始节点的默认值。

## 现场

表单、定时任务、子工作流常把没填的格子交成空串。此前它照样盖掉开始节点里写好的默认值(with_run_params 与
执行时的 `{**默认, **参数}`),必填检查接着说缺参数 —— 用户明明在开始节点里填过;不是必填的,就拿着空值往下跑。
"""

from __future__ import annotations

import pytest

from tests.util import fresh_client, wait_status


def _workflow(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "写稿", "graph": {
        "nodes": [
            {"id": "start", "type": "start",
             "config": {"params": {"topic": "默认主题", "tone": "轻松"}, "required_params": "topic"}},
            {"id": "t", "type": "template", "config": {"template": "{{start.topic}}/{{start.tone}}/{{start.extra}}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "t"}],
    }}).json()
    return ws, workflow["id"]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_空的运行参数不盖默认值_没声明的空参数照旧留着(blank) -> None:
    client = fresh_client()
    _ws, workflow_id = _workflow(client)
    started = client.post(f"/api/workflows/{workflow_id}/run",
                          json={"params": {"topic": blank, "tone": blank, "extra": ""}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    context = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert context["t"]["text"] == "默认主题/轻松/"


def test_给了值的照旧盖默认值() -> None:
    client = fresh_client()
    _ws, workflow_id = _workflow(client)
    started = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {"topic": "猫", "extra": "x"}})
    assert wait_status(client, started.json()["id"]) == "succeeded"
    context = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert context["t"]["text"] == "猫/轻松/x"
