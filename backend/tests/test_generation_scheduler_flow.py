from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job
from app.main import app
from tests.util import fresh_client


def _configure(client, vendor: str, name: str, models: list[tuple[str, list[str]]], **config: str) -> str:
    """配一条连接 + 若干模型。生成选项现在完全来自用户配置(不再有内置目录表),
    所以每个用到生成的用例都得先配 —— 这本身就是新语义的一部分:没配过就没得选。"""
    response = client.post(
        "/api/settings/providers", json={"name": name, "vendor": vendor, "config": config}
    )
    assert response.status_code < 300, response.text
    profile = response.json()
    for model_id, caps in models:
        added = client.post(
            f"/api/settings/providers/{profile['id']}/models",
            json={"model_id": model_id, "enabled": True, "capability_ids": caps},
        )
        assert added.status_code < 300, added.text
    return profile["id"]


def reset_db(tmp_path: Path) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_generation_job_creates_job_and_generation_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 不真起生成线程:这条用例断言的是"任务建出来了",而真跑会拿假 key 去打网络,
    # 线程里的异常还会飘到后面的用例里(实测污染了同文件的下一条)。
    monkeypatch.setattr("app.api.routes.generation.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    _configure(client, "alibaba", "百炼", [("qwen-image", ["image"])], api_key="k")
    models = client.get("/api/generation/options?kind=image").json()
    assert any(model["model"] == "qwen-image" for model in models)
    assert all(model["adapter_available"] for model in models)

    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "provider": "alibaba",
            "model": "qwen-image",
            "kind": "image",
            "prompt": "A clean professional video editor interface",
            "negative_prompt": "blurry",
            "parameters": {"size": "1024x1024"},
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["job"]["kind"] == "ai_generation"
    assert payload["job"]["status"] == "queued"
    assert payload["generation"]["job_id"] == payload["job"]["id"]
    assert payload["generation"]["request"]["prompt"].startswith("A clean")
    assert payload["generation"]["request"]["negative_prompt"] == "blurry"
    assert payload["generation"]["session_id"] is not None
    assert payload["generation"]["created_at"]
    assert payload["generation"]["updated_at"]


def test_generation_models_expose_provider_specific_parameters() -> None:
    """参数描述符按 (vendor, model, kind) 查静态表 —— 它是关于供应商 API 的知识,
    不是用户配置,所以不该在库里占一行。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 首个账号即实例管理员,配供应商要它
    _configure(client, "openai-compatible", "兼容端点", [("gpt-image-2", ["image"])], base_url="http://x/v1", api_key="k", default_model="gpt-image-2")
    _configure(client, "alibaba", "百炼", [("qwen-image-edit", ["image"])], api_key="k")
    by_model = {m["model"]: m for m in client.get("/api/generation/options?kind=image").json()}

    openai_sizes = by_model["gpt-image-2"]["capabilities"]["sizes"]
    assert "1024x1024" in openai_sizes
    assert "1024x576" not in openai_sizes

    qwen_edit_caps = by_model["qwen-image-edit"]["capabilities"]
    assert qwen_edit_caps["parameter_keys"] == ["reference_image"]
    assert qwen_edit_caps["max_num_images"] == 1


def test_没配过就没得选() -> None:
    """新语义:生成选项 = 用户配了什么。以前不管配没配,内置目录都会铺一堆出来,
    点下去才发现没有对应的供应商档案。"""
    client = fresh_client()
    assert client.get("/api/generation/options?kind=image").json() == []


def test_generation_sessions_scope_jobs_and_can_be_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.generation.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    _configure(client, "alibaba", "百炼", [("qwen-image", ["image"])], api_key="k")
    session = client.post("/api/generation/sessions", json={"workspace_id": ws["id"], "title": "海边女孩"}).json()
    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "session_id": session["id"],
            "provider": "alibaba",
            "model": "qwen-image",
            "kind": "image",
            "prompt": "海边女孩",
            "parameters": {"size": "320x180"},
        },
    )

    assert res.status_code == 200
    generation = res.json()["generation"]
    assert generation["session_id"] == session["id"]
    scoped = client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session['id']}").json()
    assert [item["id"] for item in scoped] == [generation["id"]]

    profile = client.post(
        "/api/settings/providers",
        json={
            "name": "OpenAI compatible",
            "vendor": "openai-compatible",
            "config": {
                "api_key": "sk-test",
                "base_url": "https://example.test/v1",
                "default_model": "gpt-image-2",
            },
        },
    ).json()
    renamed = client.patch(f"/api/generation/sessions/{session['id']}", json={"title": "女孩分镜"}).json()
    assert renamed["title"] == "女孩分镜"
    configured = client.patch(
        f"/api/generation/sessions/{session['id']}",
        json={"provider_profile_id": profile["id"], "model": "gpt-image-2", "kind": "image"},
    ).json()
    assert configured["provider_profile_id"] == profile["id"]
    assert configured["model"] == "gpt-image-2"
    assert client.delete(f"/api/generation/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session['id']}").status_code == 404


def test_generation_jobs_are_listed_by_job_created_time_not_uuid() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    session = client.post("/api/generation/sessions", json={"workspace_id": ws["id"], "title": "顺序"}).json()

    with SessionLocal() as db:
        db.add_all(
            [
                Job(
                    id="job-old",
                    workspace_id=ws["id"],
                    kind="ai_generation",
                    status="succeeded",
                    created_at=datetime(2026, 1, 1, 10, 0, 0),
                ),
                Job(
                    id="job-new",
                    workspace_id=ws["id"],
                    kind="ai_generation",
                    status="succeeded",
                    created_at=datetime(2026, 1, 1, 10, 1, 0),
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                GenerationJob(
                    id="a-old",
                    workspace_id=ws["id"],
                    session_id=session["id"],
                    job_id="job-old",
                    provider="alibaba",
                    model="qwen-image",
                    kind="image",
                    request={"prompt": "old"},
                ),
                GenerationJob(
                    id="z-new",
                    workspace_id=ws["id"],
                    session_id=session["id"],
                    job_id="job-new",
                    provider="alibaba",
                    model="qwen-image",
                    kind="image",
                    request={"prompt": "new"},
                ),
            ]
        )
        db.commit()

    scoped = client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session['id']}").json()

    assert [item["request"]["prompt"] for item in scoped] == ["old", "new"]


def test_scheduled_task_run_creates_job(tmp_path: Path) -> None:
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "Nightly render",
            "kind": "render",
            "trigger_type": "interval",
            "schedule": {"seconds": 3600},
            "payload": {"sequence_id": "seq_1"},
        },
    ).json()

    assert task["next_run_at"] is not None

    res = client.post(f"/api/scheduled-tasks/{task['id']}/run")
    assert res.status_code == 200
    payload = res.json()
    assert payload["run"]["scheduled_task_id"] == task["id"]
    assert payload["job"]["kind"] == "render"
    assert payload["job"]["payload"]["scheduled_task_id"] == task["id"]


def test_clearing_finished_jobs_keeps_generation_history() -> None:
    """生成记录是创作历史:任务中心「清空已完成」删 job 后,记录必须还在
    (job_id 置空),会话列表接口也仍要返回它。曾因 CASCADE 全部丢失。"""
    from app.domain.jobs import create_job
    from app.db.models import GenerationSession, User

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    with SessionLocal() as db:
        # 会话得有主人 —— 没有主人的会话谁都看不见(见 domain/sharing)。
        me = db.query(User).order_by(User.created_at).first()
        session = GenerationSession(workspace_id=ws["id"], title="夜景素材", owner_user_id=me.id)
        db.add(session)
        db.flush()
        job = create_job(db, workspace_id=ws["id"], kind="ai_generation", payload={}, message="done")
        job.status = "succeeded"
        generation = GenerationJob(
            workspace_id=ws["id"], session_id=session.id, job_id=job.id,
            provider="volcengine", model="doubao-seedance", kind="video", request={"prompt": "海边"},
        )
        db.add(generation)
        db.commit()
        session_id, generation_id = session.id, generation.id

    removed = client.delete(f"/api/jobs/finished?workspace_id={ws['id']}").json()
    assert removed["removed"] >= 1

    listed = client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session_id}").json()
    assert [g["id"] for g in listed] == [generation_id]
    assert listed[0]["job_id"] is None  # job 没了,记录还在


def test_generation_jobs_surface_cost(tmp_path: Path) -> None:
    """生成结果带出计费:有已知费用显金额;有事件但无定价显 unknown;无事件为空。"""
    from app.domain.usage import record_usage

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        g1 = GenerationJob(workspace_id=ws["id"], provider="alibaba", model="qwen-image", kind="image", request={"prompt": "a"})
        g2 = GenerationJob(workspace_id=ws["id"], provider="x", model="y", kind="image", request={"prompt": "b"})
        g3 = GenerationJob(workspace_id=ws["id"], provider="x", model="z", kind="image", request={"prompt": "c"})
        db.add_all([g1, g2, g3])
        db.flush()
        record_usage(db, workspace_id=ws["id"], capability="image", operation="generation_job",
                     source_type="generation_job", source_id=g1.id, idempotency_key=f"generation:{g1.id}:succeeded",
                     cost_micros=12345, currency="CNY", cost_confidence="estimated")
        record_usage(db, workspace_id=ws["id"], capability="image", operation="generation_job",
                     source_type="generation_job", source_id=g2.id, idempotency_key=f"generation:{g2.id}:succeeded",
                     cost_micros=None, currency="CNY")
        db.commit()
        ids = (g1.id, g2.id, g3.id)

    jobs = {j["id"]: j for j in client.get(f"/api/generation/jobs?workspace_id={ws['id']}").json()}
    assert jobs[ids[0]]["cost_micros"] == 12345 and jobs[ids[0]]["currency"] == "CNY" and jobs[ids[0]]["cost_confidence"] == "estimated"
    assert jobs[ids[1]]["cost_micros"] is None and jobs[ids[1]]["cost_confidence"] == "unknown"
    assert jobs[ids[2]]["cost_micros"] is None and jobs[ids[2]]["cost_confidence"] is None




def test_设置页加了什么_生成页就有什么() -> None:
    """这条钉住这次重构的目的:两个页面同一个来源。

    以前生成页看 generation_models(内置目录)、设置页看 provider_models,于是 ComfyUI 的
    工作流只在生成页出现(还是个叫 `workflow` 的假模型 id),而设置页里新加的模型进不了生成页。
    """
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = _configure(
        client, "comfyui", "本地 ComfyUI", [("my-flow.json", ["image", "video"])], base_url="http://127.0.0.1:1"
    )

    for kind in ("image", "video"):
        options = client.get(f"/api/generation/options?kind={kind}").json()
        assert [(o["provider_profile_id"], o["model"]) for o in options] == [(profile_id, "my-flow.json")]

    # 在设置里停用 → 生成页立刻没有了(同一个来源的直接后果)
    client.patch(
        f"/api/settings/providers/{profile_id}/models/my-flow.json", json={"enabled": False}
    )
    assert client.get("/api/generation/options?kind=image").json() == []


def test_描述符按模型查_查不到给保守兜底() -> None:
    """参数描述符是关于供应商 API 的静态知识。目录里没登记的模型(私有部署、别名、
    ComfyUI 的任意工作流名)照样要能给出一组可用参数 —— 缺描述符不等于不能用。"""
    from app.domain.generation import capabilities_for

    assert capabilities_for("bytedance", "doubao-seedance-2-0-260128", "video")["resolutions"]
    # 同 vendor 同 kind 的兜底
    assert capabilities_for("comfyui", "随便什么名字.json", "image")["sizes"]
    # 完全不认识的 vendor
    assert capabilities_for("nobody", "x", "image")["default_size"] == "1024x1024"
    assert capabilities_for("nobody", "x", "video")["max_duration_seconds"] == 10
