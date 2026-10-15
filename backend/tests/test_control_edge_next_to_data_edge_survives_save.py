"""画布上用户亲手连的「数据边 + 控制边」同一对节点,保存后两条边都得在。

## 现场

维护者在画布上给同一对节点连了数据边(虚线,d- 前缀)和控制边(实心紫,e- 前缀)。两张截图对照:
刷新之后,**凡某对节点间有数据边的,那条控制边就没了**(workflow 0b49995914c344728cf04428c859ffe7,
库里的 edges 只剩 e-start-llm-1、e-llm-1-llm-2 和几条 d- 边)。工作流能跑出结果说明控制边一度在
编辑器内存里 —— 丢的那一下在保存路上。

## 根因

规范化(normalization.canonicalize_data_bindings)把「同一对节点间另有数据边」的无 handle 控制边
当多余的折掉 —— 这个折叠本来只为**这一步自己刚升级的**精确引用(`{{A.text}}` 旧写法)服务:数据边
是规范化替作者补的,控制边才成了多余。可它看的是图里**已有**的数据边:用户亲手连的数据边一样让
控制边被折。折掉之后画布与库里分岔 —— 本轮画布还在(认自己刚存的那一版,不重建),刷新后控制边
就没了。

## 修法

只折「这一步刚从精确引用升级出来的数据边」导致的冗余控制边;用户画布里本来就有的数据边,
不替用户把控制边折掉。
"""

from __future__ import annotations

from tests.util import fresh_client


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "llm-1", "type": "template", "config": {"template": "写稿"}},
            {"id": "llm-2", "type": "template", "config": {"template": "改写"}},
        ],
        "edges": [
            {"id": "e-start-llm-1", "source": "start", "target": "llm-1"},
            {"id": "e-llm-1-llm-2", "source": "llm-1", "target": "llm-2"},
            #: 同一对节点上用户亲手连的两条边:数据边 + 控制边。
            {
                "id": "d-llm-1-text-llm-2-template",
                "source": "llm-1",
                "target": "llm-2",
                "kind": "data",
                "source_output": "text",
                "target_input": "template",
            },
            {"id": "e-llm-1-llm-2", "source": "llm-1", "target": "llm-2"},
        ],
    }


def _save(client, ws: str, graph: dict) -> dict:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "双连线", "graph": graph}).json()


def test同一对节点上用户连了数据边和控制边_保存后两条边都在() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    saved = _save(client, ws, _graph())
    pairs = {(edge["source"], edge["target"], edge.get("kind", "control")) for edge in saved["graph"]["edges"]}
    assert ("llm-1", "llm-2", "data") in pairs, "数据边该原样在"
    assert ("llm-1", "llm-2", "control") in pairs, "控制边是用户在画布上画的,保存不许丢 —— 丢了下一次刷新它就没了"


def test再存一遍也还在_不和库里的图分岔() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    saved = _save(client, ws, _graph())
    # 编辑器自动保存每次发整图;把库里这份(含两条边)再存回去,规范化不该越存越少。
    again = client.patch(
        f"/api/workflows/{saved['id']}",
        json={"graph": saved["graph"], "base_graph_hash": saved["graph_hash"]},
    ).json()
    pairs = {(edge["source"], edge["target"], edge.get("kind", "control")) for edge in again["graph"]["edges"]}
    assert ("llm-1", "llm-2", "control") in pairs
