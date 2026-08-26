"""工作流也能编排时间线了。

此前工作流只有「导出时间线」—— 于是「生成素材 → 编排 → 导出」这条最常见的链路,中间那步
在画布上做不了,必须切去对话里或者手动摆。而智能体早就有 edit_timeline。

**两侧认的是同一份操作清单**(domain/sequences/operations.EDIT_OP_KINDS)。那段派发逻辑
原本长在 domain/agent/confirmations 里 —— 它和智能体没有关系,那只是第一个用到它的地方;
工作流要用同一套,要么 import 智能体域(方向反了),要么抄一份(于是两处会漂)。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Sequence, Track, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _setup() -> tuple[str, str, str]:
    """建一个工作区 + 项目 + 一条带轨道的序列。返回 (workspace, sequence, track)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}
    ).json()
    with SessionLocal() as db:
        track = db.query(Track).filter(Track.sequence_id == sequence["id"]).first()
        return ws, sequence["id"], track.id if track else ""


def _run(node: str, ws: str, config: dict) -> dict:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        handler = get_executor(node)
        assert handler is not None, f"{node} 没有执行器"
        return handler(db, workflow, config)


class Test编排:
    def test_加一条轨道(self) -> None:
        ws, sequence_id, _ = _setup()
        out = _run("edit_timeline", ws, {
            "sequence_id": sequence_id,
            "operations": [{"kind": "add_track", "track_kind": "video"}],
        })
        assert out["applied"] == 1
        with SessionLocal() as db:
            assert db.query(Track).filter(Track.sequence_id == sequence_id).count() >= 2

    def test_一次多条操作(self) -> None:
        """一个节点一次提交多步 —— 每步一个节点的话,一条十步的编排要在画布上摆十个框。"""
        ws, sequence_id, _ = _setup()
        out = _run("edit_timeline", ws, {
            "sequence_id": sequence_id,
            "operations": [
                {"kind": "add_track", "track_kind": "video"},
                {"kind": "add_track", "track_kind": "audio"},
            ],
        })
        assert out["applied"] == 2

    def test_接住上游给的_JSON_文本(self) -> None:
        """上游常常是 code 节点或 LLM,它们给的是一段字符串 —— 不接住的话还得再加一个解析节点。"""
        ws, sequence_id, _ = _setup()
        out = _run("edit_timeline", ws, {
            "sequence_id": sequence_id,
            "operations": '[{"kind": "add_track", "track_kind": "video"}]',
        })
        assert out["applied"] == 1

    def test_坏_JSON_说得明白(self) -> None:
        ws, sequence_id, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="JSON"):
            _run("edit_timeline", ws, {"sequence_id": sequence_id, "operations": "{不是数组"})

    def test_空操作拦下(self) -> None:
        ws, sequence_id, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="非空"):
            _run("edit_timeline", ws, {"sequence_id": sequence_id, "operations": []})

    def test_不认识的操作说得明白(self) -> None:
        ws, sequence_id, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="不认识"):
            _run("edit_timeline", ws, {"sequence_id": sequence_id, "operations": [{"kind": "随便编一个"}]})


class Test检视:
    def test_读出轨道与时长(self) -> None:
        ws, sequence_id, _ = _setup()
        out = _run("inspect_sequence", ws, {"sequence_id": sequence_id})
        assert out["sequence_id"] == sequence_id
        assert isinstance(out["tracks"], list)
        assert out["duration"] >= 0

    def test_跨工作区不给(self) -> None:
        """节点跑在某个工作区里,而 sequence_id 可能来自上游任何地方。"""
        ws, sequence_id, _ = _setup()
        from app.db.models import Workspace

        with SessionLocal() as db:
            other = Workspace(name="别人的")
            db.add(other)
            db.commit()
            workflow = Workflow(workspace_id=other.id, name="W", graph={"nodes": [], "edges": []})
            db.add(workflow)
            db.commit()
            handler = get_executor("inspect_sequence")
            assert handler is not None
            with pytest.raises(WorkflowDomainError, match="工作区"):
                handler(db, workflow, {"sequence_id": sequence_id})


def test_两侧用的是同一份操作清单() -> None:
    """不是抄的,是同一个常量 —— 抄一份的话,加一种操作时两处会漂。"""
    from app.domain.agent.confirmations import EDIT_OP_KINDS as agent_kinds
    from app.domain.sequences.operations import EDIT_OP_KINDS as domain_kinds

    assert agent_kinds is domain_kinds
