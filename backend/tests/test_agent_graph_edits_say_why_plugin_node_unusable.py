"""智能体改图时,用不了的插件节点按**真实原因**报。

开卡前的干跑(confirmable.automation._check_graph)此前只给了 extra_types、没给 explain_plugin_node:
插件装着、连接停用了或工具没勾选,卡上只剩一句「某插件的节点用不了」,该去哪儿修全靠猜 ——
开跑前那一道(engine.start_workflow_job)早就会逐条说了。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import PluginInstance
from app.domain.plugins import instances as inst
from tests.test_plugin_nodes_hold_what_they_declare import PACKAGE, _install
from tests.util import fresh_client, user_id


def test_工具没勾选_改图卡当场说是没勾选(tmp_path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    instance_id = _install(tmp_path, user_id())
    with SessionLocal() as db:
        inst.set_exposed(db, db.get(PluginInstance, instance_id), {"join": False})
        db.commit()

    #: 整份图带着插件节点(create / update_workflow 都是这一道;edit_workflow 的 add_node 只认内置节点)。
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "create_workflow", "requested_by": "pi",
        "payload": {"name": "插件流", "graph": {
            "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
                      {"id": "j", "type": f"plugin.{PACKAGE}.join", "config": {}}],
            "edges": [{"id": "e", "source": "start", "target": "j"}]}},
    })

    assert card.status_code >= 400, card.text
    detail = card.text
    assert "勾选" in detail and "我的列表器" in detail, detail
