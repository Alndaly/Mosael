"""智能体往代码字段里写 `{{…}}`、或者把数据边接到代码字段上:开卡就拒,告诉它改用 input。

## 现场

代码字段(「代码」的 code、「执行脚本」的 expression)不插值:`{{…}}` 原样留在代码里。智能体的卡此前用
保存那一档校验(require_config=False),两样都放行 —— 而工具说明还写着「字符串值都可以写 {{node.output}}」。
用户批准之后,代码里读到的是一串字面量。
"""

from __future__ import annotations

from tests.util import fresh_client


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "流程", "graph": {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"x": "1"}}},
            #: 人手写的、在拼一段 Mustache 模板:代码里的 {{…}} 是字面量,保存放行。
            {"id": "mustache", "type": "code", "config": {"code": 'output = "{{name}}"'}},
        ],
        "edges": [],
    }})
    assert workflow.status_code == 200, workflow.text
    return client, ws, workflow.json()


def _edit(client, ws: str, workflow_id: str, operations: list[dict]):
    return client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "edit_workflow", "requested_by": "pi",
        "payload": {"workflow_id": workflow_id, "operations": operations},
    })


def test_代码里写引用_开卡就拒_说清改用input() -> None:
    client, ws, workflow = _setup()
    refused = _edit(client, ws, workflow["id"], [
        {"kind": "add_node", "type": "code", "node_id": "py", "config": {"code": "output = '{{start.x}}' * 2"}},
    ])
    assert refused.status_code == 422, refused.text
    #: 说清是哪个节点的哪一格(按标题和界面上的名字;图里已经有一个没起名的代码节点,撞名的带上 id),以及改用 input。
    assert refused.json()["detail"].startswith("「代码(py)」的代码字段「代码」里写了上游引用"), refused.text
    assert "代码里读 input" in refused.json()["detail"]

    fine = _edit(client, ws, workflow["id"], [
        {"kind": "add_node", "type": "code", "node_id": "py",
         "config": {"code": "output = inputs['x'] * 2", "input": {"x": "{{start.x}}"}}},
    ])
    assert fine.status_code == 200, fine.text


def test_数据边接到代码字段_开卡就拒() -> None:
    client, ws, workflow = _setup()
    refused = _edit(client, ws, workflow["id"], [
        {"kind": "add_node", "type": "code", "node_id": "py", "config": {"code": "output = 1"}},
        {"kind": "connect_data", "source": "start", "source_output": "x", "target": "py", "target_input": "code"},
    ])
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"].startswith("「代码(py)」的代码字段「代码」接了上游"), refused.text


def test_图里人手写的字面量不挡智能体别的改动() -> None:
    client, ws, workflow = _setup()
    fine = _edit(client, ws, workflow["id"], [{"kind": "set_node_name", "node_id": "mustache", "name": "拼模板"}])
    assert fine.status_code == 200, fine.text
    approved = client.post(f"/api/confirmations/{fine.json()['id']}/approve")
    assert approved.status_code == 200, approved.text


def test_整图替换和新建也一样拒() -> None:
    client, ws, workflow = _setup()
    graph = {"nodes": [
        {"id": "start", "type": "start", "config": {"params": {}}},
        {"id": "js", "type": "browser_evaluate", "config": {"session": "s", "expression": "'{{start.x}}'"}},
    ], "edges": []}
    for tool, payload in (
        ("update_workflow", {"workflow_id": workflow["id"], "graph": graph}),
        ("create_workflow", {"name": "新的", "graph": graph}),
    ):
        refused = client.post("/api/confirmations", json={
            "workspace_id": ws, "tool": tool, "requested_by": "pi", "payload": payload,
        })
        assert refused.status_code == 422, (tool, refused.text)
        assert refused.json()["detail"].startswith("「浏览器·执行脚本」的代码字段「表达式」里写了上游引用"), refused.text
