"""生成记录这一轮的四条迁移,各喂一份老形状的数据。

- `migrate-generation-jobs-keep-their-failure`:老表补失败原因三列;
- `backfill-generation-failures`:已经失败、任务还在的记录,把任务上的原因抄过来;
- `migrate-generation-sessions-know-their-kind`:会话按最后一次生成记下种类(AI 工作台按它分「生成」「音频」两页);
- `migrate-generation-prompts-drop-the-source-legend`:画板拼进提示词的「本次提供的素材:…」挪进 `prompt_notes`。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import (
    _backfill_generation_failures,
    _migrate_generation_jobs_keep_their_failure,
    _migrate_generation_prompts_drop_the_source_legend,
    _migrate_generation_sessions_know_their_kind,
)
from app.db.models import GenerationJob, GenerationSession, Job
from app.domain.generation.operations import prompt_for_provider
from tests.util import fresh_client, seed_assets


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("generation_jobs")}


def test_老表补上失败原因三列_老数据不动_再跑一次什么都不做() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        db.add(GenerationJob(id="g1", workspace_id=ws, provider="openai", model="m", kind="image", request={"prompt": "猫"}))
        db.commit()
    with engine.begin() as conn:
        for column in ("error", "error_key", "error_params"):
            conn.execute(text(f"ALTER TABLE generation_jobs DROP COLUMN {column}"))
    engine.dispose()
    assert not {"error", "error_key", "error_params"} & _columns()

    _migrate_generation_jobs_keep_their_failure()
    _migrate_generation_jobs_keep_their_failure()
    engine.dispose()

    assert {"error", "error_key", "error_params"} <= _columns()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT error, error_key, error_params FROM generation_jobs WHERE id = 'g1'")).one()
    assert (row[0], row[1], json.loads(row[2])) == (None, "", {})


def test_回填_只抄失败了_没产出_还没原因的() -> None:
    ws = _workspace()
    seed_assets(ws, {"made": "image"})
    with SessionLocal() as db:
        failed = Job(workspace_id=ws, kind="ai_generation", status="failed", error="No API key",
                     error_key="genErr_noApiKey", error_params={"provider": "openai"})
        succeeded = Job(workspace_id=ws, kind="ai_generation", status="succeeded")
        db.add_all([failed, succeeded])
        db.flush()
        db.add_all([
            GenerationJob(id="lost", workspace_id=ws, job_id=failed.id, provider="openai", model="m", kind="image"),
            GenerationJob(id="ok", workspace_id=ws, job_id=succeeded.id, provider="openai", model="m", kind="image",
                          result_asset_id="made"),
            GenerationJob(id="known", workspace_id=ws, job_id=failed.id, provider="openai", model="m", kind="image",
                          error="已经记过的", error_key=""),
            # 任务已经被清掉的:找不回原因了,不动。
            GenerationJob(id="cleared", workspace_id=ws, job_id=None, provider="openai", model="m", kind="image"),
        ])
        db.commit()

    _backfill_generation_failures()
    _backfill_generation_failures()

    with SessionLocal() as db:
        rows = {row.id: (row.error, row.error_key, row.error_params) for row in db.query(GenerationJob)}
    assert rows["lost"] == ("No API key", "genErr_noApiKey", {"provider": "openai"})
    assert rows["ok"] == (None, "", {})
    assert rows["known"] == ("已经记过的", "", {})
    assert rows["cleared"] == (None, "", {})


def test_会话按最后一次生成记下种类_一页之内换过模型的不动() -> None:
    ws = _workspace()
    base = datetime(2026, 9, 1)
    with SessionLocal() as db:
        db.add_all([
            # 从画板开出来的:没记种类,最后一次生成的是一首歌 → 音频页,模型跟着记上。
            GenerationSession(id="board-song", workspace_id=ws, title="a", kind=None),
            # 此前同一个选择器:先出图、后出歌,会话还记着图像 → 跟着最后那一次走。
            GenerationSession(id="mixed", workspace_id=ws, title="b", kind="image", model="gpt-image-1"),
            # 图像换成了视频:同一页,是用户的选择,不动。
            GenerationSession(id="switched", workspace_id=ws, title="c", kind="video", model="seedance"),
            # 从没生成过、没记种类:归「生成」页。
            GenerationSession(id="empty", workspace_id=ws, title="d", kind=None),
            # 从没生成过、选过音频模型:不动。
            GenerationSession(id="empty-audio", workspace_id=ws, title="e", kind="audio", model="suno"),
        ])
        db.flush()

        def generation(session: str, kind: str, model: str, minutes: int) -> GenerationJob:
            return GenerationJob(workspace_id=ws, session_id=session, provider="x", model=model, kind=kind,
                                 created_at=base + timedelta(minutes=minutes))

        db.add_all([
            generation("board-song", "audio", "suno-v5", 1),
            generation("mixed", "image", "gpt-image-1", 1),
            generation("mixed", "audio", "lyria-3", 2),
            generation("switched", "image", "gpt-image-1", 1),
        ])
        db.commit()

    _migrate_generation_sessions_know_their_kind()
    _migrate_generation_sessions_know_their_kind()

    with SessionLocal() as db:
        rows = {row.id: (row.kind, row.model) for row in db.query(GenerationSession)}
    assert rows == {
        "board-song": ("audio", "suno-v5"),
        "mixed": ("audio", "lyria-3"),
        "switched": ("video", "seedance"),
        "empty": ("image", None),
        "empty-audio": ("audio", "suno"),
    }


def test_画板拼进去的素材对照挪进补充_模型收到的一字不差() -> None:
    ws = _workspace()
    zh = "把 创作者.png 里的人放到 街景.jpg\n\n本次提供的素材:首帧 1 = gpt-image-2-client\n参考图 1 = 创作者.png"
    en = "a cat\n\nMaterials provided with this request:reference image 1 = cat.png\n\nReference documents (source material):\n\ndoc"
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind="ai_generation", status="succeeded",
                  payload={"subject": zh[:80], "request": {"prompt": zh}})
        db.add(job)
        db.flush()
        job_id = job.id
        db.add_all([
            GenerationJob(id="zh", workspace_id=ws, job_id=job_id, provider="x", model="m", kind="image",
                          request={"prompt": zh, "parameters": {}}),
            GenerationJob(id="en", workspace_id=ws, provider="x", model="m", kind="image", request={"prompt": en}),
            GenerationJob(id="plain", workspace_id=ws, provider="x", model="m", kind="image",
                          request={"prompt": "只是一句话\n\n第二段"}),
        ])
        db.commit()

    _migrate_generation_prompts_drop_the_source_legend()
    _migrate_generation_prompts_drop_the_source_legend()

    with SessionLocal() as db:
        requests = {row.id: row.request for row in db.query(GenerationJob)}
        payload = db.get(Job, job_id).payload
    assert requests["zh"] == {
        "prompt": "把 创作者.png 里的人放到 街景.jpg",
        "prompt_notes": ["本次提供的素材:首帧 1 = gpt-image-2-client\n参考图 1 = 创作者.png"],
        "parameters": {},
    }
    assert prompt_for_provider(requests["zh"]) == zh
    # 对照后面跟着的(上游文档)原样跟着挪过去:拼回去还是原来那段。
    assert requests["en"]["prompt"] == "a cat"
    assert prompt_for_provider(requests["en"]) == en
    assert requests["plain"] == {"prompt": "只是一句话\n\n第二段"}
    assert payload["request"]["prompt"] == "把 创作者.png 里的人放到 街景.jpg"
    assert payload["subject"] == "把 创作者.png 里的人放到 街景.jpg"
