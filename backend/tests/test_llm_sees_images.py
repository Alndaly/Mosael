"""大模型节点要能**看着图**回答:「要模型看的图片」那一格的图和提示词一起发过去(多模态消息)。

此前 LLM 节点只发一段文字 —— 提示词里写 `{{画图.asset_id}}`,模型收到的是一串素材编号,从没见过那张图。
走真的工作流引擎,只把最外面那一次对话请求换成桩,看发出去的消息长什么样。
"""

from __future__ import annotations

import base64
import time

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import Job, Workflow
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.revisions import attest_current_revision
from tests.util import add_provider, fresh_client, insert_asset, user_id

#: 一张 1×1 的 PNG。
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def setup(monkeypatch):
    from app.domain.workflows.executors import ai

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "看图"}).json()["id"]
    folder = settings.media_dir / "llm-images"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cat.png").write_bytes(PNG)
    image = insert_asset(workspace_id, kind="image", name="猫", file_key="media/llm-images/cat.png")
    video = insert_asset(workspace_id, kind="video", name="一段视频", file_key="media/llm-images/clip.mp4")
    with SessionLocal() as db:
        profile = add_provider(db, name="对话", vendor="openai", base_url="https://a.example/v1", api_key="k",
                               model="chat-a", capability_ids=["chat"], owner_username="tester")
        db.commit()
        profile_id = profile.id

    sent: list[list[dict]] = []

    def fake_chat(target, messages, **_kw):
        sent.append(messages)
        return "一只猫"

    monkeypatch.setattr(ai, "chat", fake_chat)

    def run(image_asset_ids: str) -> Job:
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "pic", "type": "asset", "config": {"asset_id": image}},
                {"id": "ask", "type": "llm", "config": {"profile_id": profile_id, "model": "chat-a",
                                                        "prompt": "图里是什么?", "image_asset_ids": image_asset_ids}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "pic"}, {"id": "e2", "source": "pic", "target": "ask"}],
        }
        with SessionLocal() as db:
            workflow = create_workflow(db, workspace_id=workspace_id, name="看图", graph=graph, created_by=user_id())
            db.commit()
            workflow = db.get(Workflow, workflow.id)
            attest_current_revision(db, workflow, attested_by=user_id())
            job_id = start_workflow_job(db, workflow, created_by=user_id()).id
            db.commit()
        for _ in range(200):
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job.status in ("succeeded", "failed", "cancelled"):
                    return job
            time.sleep(0.05)
        raise AssertionError("工作流没跑完")

    return run, sent, image, video


def _user_turn(messages: list[dict]) -> object:
    return next(one for one in messages if one["role"] == "user")["content"]


def test_接上游的图_图和提示词一起发给模型(setup) -> None:
    run, sent, _image, _video = setup
    job = run("{{pic.asset_id}}")
    assert job.status == "succeeded", job.error
    content = _user_turn(sent[0])
    assert isinstance(content, list), "有图时用户那一条是多模态消息,不是一段字"
    assert content[0] == {"type": "text", "text": "图里是什么?"}
    url = content[1]["image_url"]["url"]
    assert url == "data:image/png;base64," + base64.b64encode(PNG).decode(), "发过去的是那张图本身,不是素材编号"


def test_不接图_照旧只发一段字(setup) -> None:
    run, sent, _image, _video = setup
    assert run("").status == "succeeded"
    assert _user_turn(sent[0]) == "图里是什么?"


def test_给了视频_当场说清只收图片_不白花一次调用(setup) -> None:
    run, sent, _image, video = setup
    job = run(video)
    assert job.status == "failed"
    assert "一段视频" in (job.error or "") and "只收图片" in (job.error or ""), job.error
    assert sent == []


def test_不在工作区的图_说清是哪一张(setup) -> None:
    run, sent, _image, _video = setup
    job = run("no-such-asset")
    assert job.status == "failed"
    assert t("wfErr_llmImageMissing", "zh", asset_id="no-such-asset") in (job.error or ""), job.error
    assert sent == []


def test_超过张数上限_当场拦(setup) -> None:
    run, sent, image, _video = setup
    job = run(",".join([image] * 9))
    assert job.status == "failed" and "最多" in (job.error or ""), job.error
    assert sent == []
