"""节点声明要把执行体**本来就要**的东西说出来 —— 否则空着也能启动,要等跑到那一步才失败,而那时前面的付费步骤已经花了。

- 「取资产」点名(entity_id)和按名字找(name)恰好用一种,两样都空执行体报 wfErr_entityGetNeedsTarget;
  数字人出镜带货里「挑一位主播」空着,此前要等写脚本那次计费的对话跑完才失败。
- 「长稿分段配音」的音色,执行体空着就报 wfErr_talkingNeedsVoice,和「语音合成」一样是必填。
- 「新建成片项目」可以建在已有项目里:一条长视频切出来的十条竖屏,是一个项目十条时间线,不是十个项目。
"""

from __future__ import annotations

import pytest

from app.core.unit_of_work import unit_of_work
from app.db.models import Project, Sequence, Workflow
from app.domain.workflows import WorkflowDomainError, validate_graph
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _one(node_type: str, config: dict) -> list[str]:
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "n", "type": node_type, "config": config}],
        "edges": [{"id": "e", "source": "start", "target": "n"}],
    }
    return validate_graph(graph)


def test_取资产_点名和按名字找两样都空_运行前就拦() -> None:
    assert any("entity_id / name" in one for one in _one("entity_get", {"entity_id": "", "kind": "character"}))
    assert _one("entity_get", {"entity_id": "e-1"}) == []
    assert _one("entity_get", {"kind": "character", "name": "{{start.name}}"}) == []


def test_长稿分段配音没挑音色_运行前就拦() -> None:
    errors = _one("talking_segments", {"text": "大家好", "engine": "builtin:clone", "voice": ""})
    assert any("voice" in one for one in errors), errors
    assert _one("talking_segments", {"text": "大家好", "engine": "builtin:clone", "voice": "v-1"}) == []


def _workflow(ws: str) -> str:
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def test_新建成片项目可以建在已有项目里_别的工作区的项目不行() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    wf, foreign_wf = _workflow(ws), _workflow(other)
    create = get_executor("project_sequence_create")
    with unit_of_work() as db:
        first = create(db, db.get(Workflow, wf), {"name": "第一条", "width": 1080, "height": 1920})
        second = create(db, db.get(Workflow, wf), {"name": "第二条", "project_id": first["project_id"]})
        db.commit()
        assert second["project_id"] == first["project_id"]
        assert db.query(Sequence).filter(Sequence.project_id == first["project_id"]).count() == 2
        #: 打开项目时仍停在它原来那条时间线上。
        assert db.get(Project, first["project_id"]).active_sequence_id == first["sequence_id"]
        with pytest.raises(WorkflowDomainError):
            create(db, db.get(Workflow, foreign_wf), {"name": "越界", "project_id": first["project_id"]})
