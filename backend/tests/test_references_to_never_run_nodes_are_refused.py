"""**会跑的节点引用了一定不会跑的节点**:点运行当场拦下,说清谁引用了谁、它为什么不会跑、怎么修。

## 现场

`{{节点.输出}}` 引用即依赖 —— 只管先后,不管该不该跑。顶层只有开始节点是入口(engine.is_entry),一个**没接进流程**
的节点每次都被跳过,引用它的下游插值成空串,工作流照样报成功。「从主题到完整视频」的「可用的 3D 道具」因此从模板 v8 到
v11 一次都没跑过:布景师拿到的道具清单永远是空的。画布上只有一个黄色的「未连接到流程」提醒,后端一声不吭。

## 拦与不拦

- 拦:会跑的节点引用了一定不会跑的节点(`{{…}}` 或数据边)。旧版模板建的整片图也在此列,文案指向「按新版重建」。
- 不拦:被引用的节点在条件分支里(可能跑可能不跑,作者有意为之);循环体 / 子图里没有入边的根(体的入口规则);
  没人引用的孤立节点(画布照旧只是提醒)。

判据本身由 contracts/workflow-never-run-cases.json 钉住(两侧各跑一遍),这里走真实的运行入口。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tests.util import fresh_client, wait_status


def _client_and_workspace() -> tuple[Any, str]:
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _save(client: Any, workspace: str, graph: dict[str, Any]) -> dict[str, Any]:
    saved = client.post("/api/workflows", json={"workspace_id": workspace, "name": "引用", "graph": graph})
    assert saved.status_code == 200, saved.text
    return saved.json()


def _run(client: Any, workflow_id: str, **headers: str) -> Any:
    return client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}}, headers=headers)


def _props_graph() -> dict[str, Any]:
    """「可用的 3D 道具」的现场,缩到三个节点:props 一条连线都没有,只靠布景提示词里的引用挂着。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"topic": "猫"}}},
            {"id": "props", "type": "template", "config": {"template": "桌子、椅子"}},
            {"id": "set_design", "type": "template",
             "config": {"template": "{{start.topic}} 的布景,道具从这里挑:{{props.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "set_design"}],
    }


def test_没接进流程的节点被引用_点运行当场拦下_文案点名谁引用了谁和怎么修() -> None:
    client, workspace = _client_and_workspace()
    #: 保存不拦:旧图照样存得下、打得开,用户才连得上它。
    workflow = _save(client, workspace, _props_graph())
    refused = _run(client, workflow["id"])
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert "set_design" in detail and "{{props.text}}" in detail, detail
    assert "props 没接进流程" in detail and "永远不会运行" in detail
    assert "按新版重建" in detail
    #: 英文界面看到的是英文。
    english = _run(client, workflow["id"], **{"Accept-Language": "en"}).json()["detail"]
    assert "Node set_design references {{props.text}}" in english
    assert "isn't wired into the flow" in english and "Rebuild from the new version" in english


def test_连进流程之后照常跑_拿到的是它的值() -> None:
    client, workspace = _client_and_workspace()
    graph = _props_graph()
    graph["edges"] += [{"id": "e0", "source": "start", "target": "props"}]
    workflow = _save(client, workspace, graph)
    started = _run(client, workflow["id"])
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    context = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert context["set_design"]["text"].endswith("桌子、椅子")


def test_整格一条的引用存成了数据边_照样拦() -> None:
    """规范化把 `{{props.text}}` 升级成数据边(配置清空)—— 引用换了一种写法,不该因此漏过去。"""
    client, workspace = _client_and_workspace()
    graph = _props_graph()
    graph["nodes"][2]["config"]["template"] = "{{props.text}}"
    workflow = _save(client, workspace, graph)
    assert any(edge.get("kind") == "data" and edge["source"] == "props" for edge in workflow["graph"]["edges"])
    refused = _run(client, workflow["id"])
    assert refused.status_code == 422, refused.text
    assert "{{props.text}}" in refused.json()["detail"] and "props 没接进流程" in refused.json()["detail"]


def test_被引用的在条件分支里_可能跑可能不跑_不拦() -> None:
    client, workspace = _client_and_workspace()
    workflow = _save(client, workspace, {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"voice": "no"}}},
            {"id": "c", "type": "condition", "config": {"left": "{{start.voice}}", "op": "equals", "right": "yes"}},
            {"id": "narration", "type": "template", "config": {"template": "画外音"}},
            {"id": "join", "type": "template", "config": {"template": "[{{narration.text}}]"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c"},
            {"id": "e2", "source": "c", "target": "narration", "source_handle": "true"},
            {"id": "e3", "source": "start", "target": "join"},
        ],
    })
    started = _run(client, workflow["id"])
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    context = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert "narration" not in context and context["join"]["text"] == "[]", "分支没走,引用出来是空串 —— 作者有意为之"


def test_没人引用的孤立节点不拦_只是不跑() -> None:
    client, workspace = _client_and_workspace()
    graph = _props_graph()
    graph["nodes"][2]["config"]["template"] = "{{start.topic}} 的布景"
    workflow = _save(client, workspace, graph)
    started = _run(client, workflow["id"])
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    assert "props" not in client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]


def _loop(body: dict[str, Any], **config: Any) -> dict[str, Any]:
    return {"id": "loop", "type": "loop_foreach", "config": {"items": "甲\n乙", "body": body, **config}}


def test_循环体里没有入边的根就是入口_被引用不拦_真的跑了() -> None:
    """体的入口规则和顶层相反:执行器跑体时无入边的节点也是入口(engine 的 entry_is_root)。"""
    client, workspace = _client_and_workspace()
    body = {
        "nodes": [
            {"id": "style", "type": "template", "config": {"template": "胶片感"}},
            {"id": "shot", "type": "template", "config": {"template": "{{loop.item}},{{style.text}}"}},
        ],
        "edges": [],
    }
    workflow = _save(client, workspace, {
        "nodes": [{"id": "start", "type": "start", "config": {}}, _loop(body, output="{{shot.text}}")],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    })
    started = _run(client, workflow["id"])
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    context = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert context["loop"]["results"] == ["甲,胶片感", "乙,胶片感"]


def test_循环节点在外层的_inputs_引用了没接进流程的节点_照样拦() -> None:
    """循环的 inputs 在外层解析:它引用的外层节点不跑,体里拿到的就是空串。体内的 body / output 属于体自己,不算。"""
    client, workspace = _client_and_workspace()
    body = {"nodes": [{"id": "props", "type": "template", "config": {"template": "{{loop.item}} {{input.props}}"}}], "edges": []}
    workflow = _save(client, workspace, {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "props", "type": "template", "config": {"template": "桌子"}},
            _loop(body, inputs={"props": "道具:{{props.text}}"}, output="{{props.text}}"),
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    })
    refused = _run(client, workflow["id"])
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert "节点 loop 引用了 {{props.text}}" in detail and "props 没接进流程" in detail, detail


def test_旧版整片模板建的图_道具没接进流程_被拦并指向按新版重建() -> None:
    """v8–v11 的「从主题到完整视频」:「可用的 3D 道具」一条连线都没有。这一类旧图整片被拦,是用户接受的 —— 文案指向重建。"""
    client, workspace = _client_and_workspace()
    created = client.post("/api/workflows", json={
        "workspace_id": workspace, "name": "整片", "template_id": "full_video_generation",
    }).json()
    old = deepcopy(created["graph"])
    old["meta"]["template_version"] = 11
    old["edges"] = [edge for edge in old["edges"] if "props" not in (edge["source"], edge["target"])]
    workflow = _save(client, workspace, old)
    refused = _run(client, workflow["id"])
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert "节点 set_design 引用了 {{props.catalog}},可节点 props 没接进流程" in detail, detail
    assert "按新版重建" in detail
