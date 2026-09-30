"""译配选了「只去掉人声」,没有分离能力要在**任何节点花钱之前**说。

此前这句只在配音节点开始时问(start_subtitle_dub → ensure_original_audio_mode);译配模板里它排在转写、
付费翻译之后 —— 翻译的钱花完了才说「装不了分离引擎,这条做不了」。现在节点登记运行前检查
(executors.register_preflight),引擎建任务之前对图里每个配音节点问一遍,循环体、子图里的也算。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.templates import translated_dub_graph
from tests.util import fresh_client, user_id


def _workflow(graph: dict) -> tuple[str, str]:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=workspace, name="译配", graph=graph, created_by=user_id())
        db.commit()
        return workspace, workflow.id


def _start(workflow_id: str) -> None:
    from app.db.models import Workflow

    with SessionLocal() as db:
        start_workflow_job(db, db.get(Workflow, workflow_id), created_by=user_id())
        db.commit()


def _ready_graph() -> dict:
    graph = translated_dub_graph(voice_id="v1")
    next(one for one in graph["nodes"] if one["id"] == "source_video")["config"]["asset_id"] = "some-video"
    return graph


def test_没有分离能力_译配在转写和翻译之前就拒_一个任务都不建(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.assets import separation

    monkeypatch.setattr(separation, "available", lambda *_a, **_k: False)
    workspace, workflow_id = _workflow(_ready_graph())
    with pytest.raises(WorkflowDomainError) as refused:
        _start(workflow_id)
    assert refused.value.key == "dubErr_separationUnavailableForMode"
    with SessionLocal() as db:
        assert list(db.scalars(select(Job).where(Job.workspace_id == workspace))) == [], "没排任何节点:转写、翻译都没花钱"


def test_预检按跑的人挑提供方(monkeypatch: pytest.MonkeyPatch) -> None:
    """配音那一步挑分离能力看的是跑的人(他定过的插件也算),预检同一个人。"""
    from app.domain.assets import separation

    asked: list = []
    monkeypatch.setattr(separation, "available", lambda _db, owner, *_a: asked.append(owner) or False)
    _workspace, workflow_id = _workflow(_ready_graph())
    with pytest.raises(WorkflowDomainError):
        _start(workflow_id)
    assert asked == [user_id()]


def test_原声处理是引用或不是只去掉人声_预检不拦(monkeypatch: pytest.MonkeyPatch) -> None:
    """引用的值要到运行时才知道,不在这里猜;选了静音 / 压低的根本用不着分离。"""
    from app.domain.workflows.executors import run_preflights

    monkeypatch.setattr("app.domain.assets.separation.available", lambda *_a, **_k: False)
    for mode in ("mute", "duck", "{{start.original_audio}}"):
        graph = _ready_graph()
        next(one for one in graph["nodes"] if one["id"] == "dubbing")["config"]["original_audio"] = mode
        with SessionLocal() as db:
            run_preflights(db, graph, None)

    #: 循环体里的配音节点也查。
    body = _ready_graph()
    wrapper = {"nodes": [{"id": "loop", "type": "loop_foreach", "config": {"body": body}}], "edges": []}
    with SessionLocal() as db, pytest.raises(WorkflowDomainError):
        run_preflights(db, wrapper, None)
