"""生成任务结果里「每份用的参数」记在 `output_parameters`,不占 `outputs`。

`outputs` 是「这个任务交回了什么」(`[{type, …}]`):画板回执(boards.outputs.outputs_of)和任务详情只认它,看见它就不再看
`asset_ids`。生成任务此前把每张的种子对照 `[{asset_id, parameters}]` 也记在 `outputs` 下 —— ComfyUI 跑几遍的生成在画板上
落成「任务结束了,但没有交回任何产出」,任务详情一张图都不显示。老记录由迁移挪过去。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_generation_results_keep_output_parameters_apart
from app.db.models import Job
from app.domain.boards.outputs import outputs_of
from tests.util import fresh_client


def _job(workspace_id: str, job_id: str, kind: str, result: dict) -> None:
    with SessionLocal() as db:
        db.add(Job(id=job_id, workspace_id=workspace_id, kind=kind, status="succeeded", payload={}, result=result))
        db.commit()


def test_老的生成结果_每份参数挪出outputs_交回的素材又认得出了_重跑不变() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    pairs = [{"asset_id": "a1", "parameters": {"seed": 7}}, {"asset_id": "a2", "parameters": {"seed": 8}}]
    _job(ws, "gen-old", "ai_generation", {"asset_ids": ["a1", "a2"], "outputs": pairs, "note": "跑了 2 遍"})
    #: 别的任务的 `outputs` 本来就是「交回了什么」,不动
    board = [{"type": "asset", "asset_id": "b1"}]
    _job(ws, "board-run", "board_node", {"outputs": board})
    with SessionLocal() as db:
        assert outputs_of(db.get(Job, "gen-old")) == [], "迁移之前:素材被那份对照挡住了"

    _migrate_generation_results_keep_output_parameters_apart()
    _migrate_generation_results_keep_output_parameters_apart()

    with SessionLocal() as db:
        old = db.get(Job, "gen-old")
        assert old.result == {"asset_ids": ["a1", "a2"], "output_parameters": pairs, "note": "跑了 2 遍"}
        assert outputs_of(old) == [{"type": "asset", "asset_id": "a1"}, {"type": "asset", "asset_id": "a2"}]
        assert db.get(Job, "board-run").result == {"outputs": board}
    with engine.begin() as conn:
        raw = conn.execute(text("SELECT result FROM jobs WHERE id = 'gen-old'")).scalar_one()
    assert "outputs" not in (json.loads(raw) if isinstance(raw, str) else raw)
