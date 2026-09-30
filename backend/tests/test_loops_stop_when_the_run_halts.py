"""一个节点失败了,旁边的循环不再一项一项跑完。

## 现场

「停」的信号(workflows.run_scope)只有节点里的「等」看(common.wait_until)。循环体、子图的那一层
调度只看外层任务在库里的状态,循环自己的并发调度只认自己的失败,顺序跑的那一支什么都不看 ——
兄弟节点 0.3 秒就失败了、整条工作流已经判了失败,遍历循环照样把 20/20 跑完,每一项都在计费。
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import engine as wf_engine
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _workflow_id() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="停", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _patch_executors(monkeypatch) -> dict:
    """「失败」和「计一项」两种节点。只换掉叶子的行为 —— 调度、循环、体的内核都是真的。"""
    runs = {"n": 0}
    lock = threading.Lock()

    def fail(db, scope, config):
        time.sleep(0.3)
        raise WorkflowDomainError("兄弟节点失败了")

    def count(db, scope, config):
        with lock:
            runs["n"] += 1
        time.sleep(0.2)
        return {"text": "ok"}

    fakes = {"x_fail": fail, "x_count": count}
    monkeypatch.setattr(wf_engine, "get_executor", lambda kind: fakes.get(kind) or get_executor(kind))
    return runs


def _graph(loop_config: dict, loop_type: str = "loop_foreach") -> dict:
    body = {"nodes": [{"id": "c", "type": "x_count", "config": {}}], "edges": []}
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "f", "type": "x_fail", "config": {}},
            {"id": "L", "type": loop_type, "config": {"body": body, **loop_config}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "f"}, {"id": "e2", "source": "start", "target": "L"}],
    }


@pytest.mark.parametrize(
    ("loop_type", "loop_config"),
    [
        ("loop_foreach", {"items": list(range(20))}),
        ("loop_foreach", {"items": list(range(20)), "concurrency": 2}),
        ("loop_while", {"condition": "{{c.text}}", "max_iterations": 20}),
    ],
    ids=["顺序遍历", "并发遍历", "条件循环"],
)
def test_兄弟节点失败后循环不再开始下一项(monkeypatch, loop_type: str, loop_config: dict) -> None:
    runs = _patch_executors(monkeypatch)
    wf_id = _workflow_id()
    started = time.monotonic()
    with pytest.raises(WorkflowDomainError, match="兄弟节点失败了"):
        wf_engine.execute_graph(_graph(loop_config, loop_type), wf_id=wf_id)
    # 0.3 秒失败,每项 0.2 秒:失败那一刻在跑的那一两项跑完就停。此前是 20 项全跑完(4 秒)。
    assert runs["n"] <= 4, f"兄弟节点失败后循环仍跑了 {runs['n']}/20 项"
    assert time.monotonic() - started < 3


def test_一项都没失败_却有没开始的_不交出缺了几项的结果(monkeypatch) -> None:
    """并发遍历里被停下的那些项是「没开始」,不是「失败」:此前 guarded 只认自己的停,这里要是
    只跳过不报,循环会交出一份中间夹着 None 的结果。"""
    from app.domain.workflows.executors import loops
    from app.domain.workflows.run_scope import halt_scope

    started: list[int] = []

    def iterate(index, item):
        started.append(index)
        halt.set()  # 第一项跑着的时候,这一轮被叫停了
        time.sleep(0.05)
        return item

    with halt_scope() as halt, pytest.raises(WorkflowDomainError) as caught:
        loops._iterate_concurrently(iterate, list(range(8)), 2)
    assert caught.value.key == "wfErr_cancelled"
    assert len(started) <= 2
