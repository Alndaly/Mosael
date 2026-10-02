"""开始节点的**选项参数**:一个启动参数可以声明一组选项(值、标签、一句说明,可带一项前置条件),只能取其中之一。

## 现场

分析类模板的「数据来源」是手填的一格:用户得自己知道要打 `tikhub` 还是 `browser`,界面上没有选项;打错一个字
(`TlkHub`、`浏览器`)静默走浏览器;选了 TikHub 却没装插件 / 没配密钥,要等认完链接、跑到 TikHub 那一步才失败。

## 现在

- 形状:开始节点 config 里的 `param_options`(参数名 → 选项列表)。没声明选项的参数照旧自由输入 —— 这是新增的一格,
  不改已有的形状。面板上那一行的默认值栏是下拉(前端 StartParamsField)。
- 保存:形状不对就拒,说清哪一格;选项点名了却没有那一行的补一行(和必填清单同一条)。
- 运行前:选项参数的值(默认值叠上这一次带的)不在选项里就拦,点名参数和可选的值;选中的那一项声明了前置条件
  (`requires`,和模板库前置条件同一个检查键、同一个判据)而此刻没备好,也当场拦,说清缺什么、或者改选哪一项。
  没选中的那几项要什么不查 —— 选浏览器的人不会被 TikHub 没配好拦住。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.workflows import WorkflowDomainError, validate_graph, with_run_params
from app.domain.workflows.engine import check_runnable
from tests.util import fresh_client, wait_status

OPTIONS = [
    {"value": "browser", "label": "内嵌浏览器", "description": "不用配置"},
    {"value": "tikhub", "label": "TikHub", "description": "需安装 TikHub 插件并配置密钥", "requires": "tikhub_account"},
]


def _graph(*, source: str = "", required: bool = True, options: Any = None) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {
                "params": {"data_source": source},
                "required_params": ["data_source"] if required else [],
                "param_options": {"data_source": deepcopy(OPTIONS) if options is None else options},
            }},
            {"id": "t", "type": "template", "config": {"template": "走{{start.data_source}}"}},
        ],
        "edges": [{"id": "e", "source": "start", "target": "t"}],
    }


def _client_and_workspace():
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _save(client, workspace: str, graph: dict[str, Any], **headers: str):
    return client.post("/api/workflows", json={"workspace_id": workspace, "name": "W", "graph": graph}, headers=headers)


def test_选项存得下_原样留着() -> None:
    client, workspace = _client_and_workspace()
    saved = _save(client, workspace, _graph(source="browser"))
    assert saved.status_code == 200, saved.text
    start = saved.json()["graph"]["nodes"][0]["config"]
    assert start["param_options"] == {"data_source": OPTIONS}


def test_选项点名了却没有那一行的_补一行() -> None:
    client, workspace = _client_and_workspace()
    graph = _graph()
    graph["nodes"][0]["config"]["param_options"]["mode"] = [{"value": "fast", "label": "快"}]
    saved = _save(client, workspace, graph)
    assert saved.status_code == 200, saved.text
    assert saved.json()["graph"]["nodes"][0]["config"]["params"] == {"data_source": "", "mode": ""}


def test_形状不对_保存就拒_说清哪一格() -> None:
    client, workspace = _client_and_workspace()
    for bad in ([], [{"label": "没有值"}], [{"value": "a", "label": "A"}, {"value": "a", "label": "又一个 A"}],
                [{"value": "tikhub", "label": "TikHub", "requires": "没有这个检查"}], "browser, tikhub"):
        refused = _save(client, workspace, _graph(options=bad))
        assert refused.status_code == 422, (bad, refused.text)
        assert "data_source" in refused.text and "param_options" in refused.text, refused.text
    english = _save(client, workspace, _graph(options=[]), **{"Accept-Language": "en"})
    assert english.status_code == 422 and "options" in english.text, english.text


def test_运行前_值不在选项里就拦_点名参数和可选的值() -> None:
    #: 此前手填的一格:打错一个字静默走浏览器。
    errors = validate_graph(with_run_params(_graph(), {"data_source": "TikHub"}))
    assert errors == ["节点 start 的参数 data_source 是「TikHub」,只能选:browser(内嵌浏览器)、tikhub(TikHub)"], errors
    assert validate_graph(with_run_params(_graph(), {"data_source": "tikhub"})) == []
    #: 没填、也不是必填:不拦(引用出来是空串,和自由输入的参数一样)。
    assert validate_graph(_graph(required=False)) == []
    #: 没填、是必填:照旧按必填说。
    assert validate_graph(_graph()) == ["节点 start 缺少必填配置 params.data_source"]


def _actor_and_workspace() -> tuple[str, str]:
    client, workspace = _client_and_workspace()
    with SessionLocal() as db:
        return db.query(User).order_by(User.created_at).first().id, workspace


def test_选了要前置条件的那一项而它没备好_运行前拦下_说清缺什么或改选哪一项() -> None:
    actor, workspace = _actor_and_workspace()
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        check_runnable(db, _graph(), {"data_source": "tikhub"}, actor, workspace_id=workspace)
    message = str(caught.value)
    assert "data_source" in message and "TikHub" in message, message
    assert "没装 TikHub 插件" in message, "这台机器上没装:说去装它"
    assert "内嵌浏览器" in message, "或者改选另一项"


def test_选了不要前置条件的那一项_不查别的选项要什么() -> None:
    actor, workspace = _actor_and_workspace()
    with SessionLocal() as db:
        check_runnable(db, _graph(), {"data_source": "browser"}, actor, workspace_id=workspace)


def test_点运行时同一道_选浏览器照常跑完() -> None:
    client, workspace = _client_and_workspace()
    workflow = _save(client, workspace, _graph()).json()
    refused = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {"data_source": "tikhub"}})
    assert refused.status_code == 422 and "TikHub" in refused.json()["detail"], refused.text
    started = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {"data_source": "browser"}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    assert client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]["t"]["text"] == "走browser"


def test_节点声明_选项由参数那一格的控件编辑() -> None:
    start = {one["type"]: one for one in fresh_client().get("/api/workflows/node-types").json()}["start"]["config"]
    assert start["params"]["options_map"] == "param_options"
    assert start["param_options"]["edited_by"] == "params"
