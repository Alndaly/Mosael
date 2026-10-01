"""插件节点用不了的时候,按**真实原因**说,开跑前按**跑的人**的插件清单判。

此前 `exposed` 把停用的连接、过期的凭据、没勾选的工具一律滤掉,报错只剩一句「没有可用的连接」,还报包 id;
开跑前的校验用的是**所有人**的插件清单 —— 别人接了、他没接的节点在那儿放行,跑到那一步才失败。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import PluginInstance
from app.domain.plugins import instances as inst
from app.domain.plugins.nodes import plugin_node_types, why_unusable
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows.engine import start_workflow_job
from tests.test_plugin_nodes_hold_what_they_declare import PACKAGE, _graph, _install
from tests.util import fresh_client, second_client, user_id


def test_没装插件() -> None:
    fresh_client()
    with SessionLocal() as db:
        reason = why_unusable(db, "plugin.dev.nobody.tool", user_id())
    assert reason is not None and reason.key == "pluginErr_nodePluginMissing"


def test_装了但他没接_说去接一个_用插件名不用包id(tmp_path) -> None:
    fresh_client()
    second_client()
    _install(tmp_path, user_id("other"))  # 连接是别人的
    with SessionLocal() as db:
        reason = why_unusable(db, f"plugin.{PACKAGE}.join", user_id())
    assert reason is not None and reason.key == "pluginErr_nodeNoConnection"
    assert "列表器" in str(reason) and PACKAGE not in str(reason)


def test_连接停用_工具没勾选_逐条说(tmp_path) -> None:
    fresh_client()
    instance_id = _install(tmp_path, user_id())
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        inst.set_exposed(db, instance, {"join": False})
        db.commit()
        reason = why_unusable(db, f"plugin.{PACKAGE}.join", user_id())
        assert reason is not None and reason.key == "pluginErr_nodeUnusable"
        assert "勾选" in str(reason) and "我的列表器" in str(reason) and "拼起来" in str(reason)
        instance.enabled = False
        db.commit()
        assert "未启用" in str(why_unusable(db, f"plugin.{PACKAGE}.join", user_id()))
        assert why_unusable(db, f"plugin.{PACKAGE}.render", user_id()) is not None


def test_被挡的连接也说工具叫什么_不露调用名(tmp_path) -> None:
    """此前连接被挡就直接跳过,没认出工具叫什么 —— 报错里露的是调用名(ComfyUI 的 `wf_<哈希>`)。"""
    fresh_client()
    instance_id = _install(tmp_path, user_id())
    with SessionLocal() as db:
        db.get(PluginInstance, instance_id).enabled = False
        db.commit()
        reason = str(why_unusable(db, f"plugin.{PACKAGE}.join", user_id()))
    assert "拼起来" in reason and "「join」" not in reason, reason


def test_工具清单没拉下来_说那个原因_不说插件更新去掉了它(tmp_path) -> None:
    """清单上没有这个工具,是因为清单上一次没刷出来(服务没开)时,该去的是把服务开起来,不是换一个工具。"""
    fresh_client()
    instance_id = _install(tmp_path, user_id())
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        inst.record_tool_list_failure(db, instance, RuntimeError("连不上 127.0.0.1:8188"))
        reason = str(why_unusable(db, f"plugin.{PACKAGE}.wf_0a1b2c", user_id()))
        assert "工具清单没拉下来" in reason and "连不上 127.0.0.1:8188" in reason, reason
        assert "插件更新后去掉了它" not in reason
        # 清单刷成功过(错清掉了):那就真是没有这个工具了
        inst.record_tool_list(db, instance, 3)
        assert "插件更新后去掉了它" in str(why_unusable(db, f"plugin.{PACKAGE}.wf_0a1b2c", user_id()))


def test_开跑前按跑的人的插件判_别人接的不算_说清原因(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    second_client()
    _install(tmp_path, user_id("other"))
    with SessionLocal() as db:
        # 所有人的清单里有它(别人接了),他自己的没有
        assert f"plugin.{PACKAGE}.join" in plugin_node_types(db, None)
        assert f"plugin.{PACKAGE}.join" not in plugin_node_types(db, user_id())
        workflow = create_workflow(db, workspace_id=ws, name="插件", graph=_graph(
            {"id": "j", "type": f"plugin.{PACKAGE}.join", "config": {}}), created_by=user_id())
        db.commit()
        with pytest.raises(WorkflowDomainError) as caught:
            start_workflow_job(db, workflow, created_by=user_id())
    message = str(caught.value)
    assert "j" in message and "还没有接" in message and "列表器" in message


def test_接口按请求方说出用不了的那几个(tmp_path) -> None:
    client = fresh_client()
    _install(tmp_path, user_id())
    with SessionLocal() as db:
        instance = db.scalars(select(PluginInstance)).one()
        inst.set_exposed(db, instance, {"render": False})
        db.commit()
    answer = client.get(
        "/api/workflows/node-types/unusable",
        params=[("types", f"plugin.{PACKAGE}.join"), ("types", f"plugin.{PACKAGE}.render"), ("types", "llm")],
    )
    assert answer.status_code == 200
    body = answer.json()
    assert [one["type"] for one in body] == [f"plugin.{PACKAGE}.render"]
    assert "勾选" in body[0]["reason"]
