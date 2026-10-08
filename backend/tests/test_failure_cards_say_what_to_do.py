"""失败卡说清楚这次是怎么回事、能做什么(维护者 2026-10-08:「生成失败」消息框太丑,要彻底重构)。

- **「重新取回」只给远端可能已经做完、是我们没拿到结果的失败**(runner.result_may_exist):成片下载断了、付费请求没等到回答、等远端
  等过了上限、等的时候后端重启了;插件生成按它说的失败的样子(`remote: pending`)。ComfyUI 已经明确报了执行错误(`remote: failed`),
  再取一次只会拿到同一个错误 —— 此前不分失败性质,失败卡上照样摆「重新取回」。
- 插件交回的失败的样子一路带到生成记录上:一句人话(「ComfyUI 执行到「KSampler」这一步出错」)、原话(详情)、认得出的原因该去哪修。
- 「再来一次」:照记着的模型和参数(连同第一次漏斗替他补的说明)重新提交一次,收在同一条会话里。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job, ProviderProfile
from app.domain.generation import runner
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client, until, user_id, wait_settled

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"
SEEDANCE = "doubao-seedance-2-0-260128"


# --- 失败的性质 → 能不能重新取回 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key, params, expected", [
    ("genErr_resultNotCollected", {"detail": "peer closed"}, True),
    ("genErr_outcomeUnknown", {"detail": "read timeout"}, True),
    ("providerErr_pollTimeout", {"task": "t", "hours": "6"}, True),
    ("jobErr_backendRestart", {}, True),
    ("providerErr_pluginFailed", {"name": "ComfyUI", "detail": "连不上 ComfyUI", "remote": "pending"}, True),
    ("providerErr_pluginFailed", {"name": "ComfyUI", "detail": "KSampler: hostbuf_file_reader_read failed", "remote": "failed"},
     False),
    ("providerErr_pluginFailed", {"name": "ComfyUI", "detail": "ComfyUI 执行失败:KSampler: x"}, False),
    ("providerErr_upstreamInvalidParams", {"vendor": "ARK", "detail": "bad size"}, False),
    ("", {}, False),
])
def test_只有远端可能做完了_我们没拿到的才值得再取(key: str, params: dict, expected: bool) -> None:
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="failed", created_by=user_id(),
                  payload={runner.REMOTE_TASK_FIELD: {"poll_path": "cgt-9"}}, error="x", error_key=key, error_params=params)
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=job.workspace_id, job_id=job.id, kind="video", provider="bytedance",
                                   model=SEEDANCE, request={"prompt": "猫", "parameters": {}})
        db.add(generation)
        db.flush()
        assert runner.can_resume(db, job), "这一家能接着取、回执也在:判据只剩失败的性质"
        assert runner.retrievable(db, generation, job) is expected


# --- ComfyUI 执行出错:端到端 ----------------------------------------------------------------------------------------------

@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
        assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
        workspace = client.post("/api/workspaces", json={"name": "ComfyUI"}).json()["id"]
        with SessionLocal() as db:
            profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
        yield client, comfy, workspace, profile_id


def _submit(client, workspace: str, profile_id: str, session_id: str | None = None) -> dict:
    submitted = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "session_id": session_id, "project_id": None, "provider_profile_id": profile_id,
        "provider": VENDOR, "model": "portrait.json", "kind": "image", "prompt": "海边的柴犬", "parameters": {},
    })
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _records(client, workspace: str, session_id: str) -> list[dict]:
    return client.get("/api/generation/jobs", params={"workspace_id": workspace, "session_id": session_id}).json()


def test_ComfyUI_报了执行错误_不摆重新取回_一句人话_原话进详情_认得出的给提示(connected) -> None:
    client, comfy, workspace, profile_id = connected
    comfy.state.outcome = "error"
    comfy.state.error_message = "hostbuf_file_reader_read failed"
    submitted = _submit(client, workspace, profile_id)
    assert wait_settled(client, submitted["job"]["id"], timeout=60) == "failed"
    [record] = _records(client, workspace, submitted["generation"]["session_id"])
    assert record["retrievable"] is False, "远端明确失败了:再取一次只会拿到同一个错误"
    assert record["error_summary"].startswith("ComfyUI 执行到「") and record["error_summary"].endswith("这一步出错")
    assert "生成失败" not in record["error_summary"] and "ComfyUI ·" not in record["error_summary"], "不重复连接名"
    assert record["error_detail"] == "KSampler: hostbuf_file_reader_read failed"
    assert record["error_hint"].startswith("这是那台 ComfyUI 上的问题") and "0.2.37" in record["error_hint"]
    english = client.get("/api/generation/jobs", params={"workspace_id": workspace,
                                                         "session_id": submitted["generation"]["session_id"]},
                         headers={"Accept-Language": "en-US"}).json()[0]
    assert english["error_summary"].startswith("ComfyUI hit an error at the") and "comfy-kitchen" in english["error_hint"]


def test_交出去之后连不上_可能照样做完_摆重新取回(connected) -> None:
    client, comfy, workspace, profile_id = connected
    comfy.state.outcome = "never"
    submitted = _submit(client, workspace, profile_id)
    assert comfy.state.submitted.wait(30), "任务交出去了"

    def following() -> bool:
        return any(method == "GET" and path.startswith("/history/") for method, path, _ in list(comfy.state.calls))

    assert until(following), "插件在等这个任务了(问过一次它的历史)"
    comfy.shutdown()
    comfy.server_close()
    assert wait_settled(client, submitted["job"]["id"], timeout=90) == "failed"
    [record] = _records(client, workspace, submitted["generation"]["session_id"])
    assert record["retrievable"] is True, "没等到 / 没拿到:远端可能照样做完"
    assert record["error_summary"] == "连不上这台 ComfyUI,确认它在运行、地址填对", "第一行是那一句"
    assert "127.0.0.1" in record["error_detail"] and "连不上" not in record["error_detail"], "地址和底层原话进详情,那一句不重复"


def test_再来一次_照记着的模型和参数重新提交_收在同一条会话里(connected) -> None:
    client, comfy, workspace, profile_id = connected
    comfy.state.outcome = "error"
    submitted = _submit(client, workspace, profile_id)
    session_id = submitted["generation"]["session_id"]
    assert wait_settled(client, submitted["job"]["id"], timeout=60) == "failed"
    [failed] = _records(client, workspace, session_id)
    assert failed["repeatable"] is True
    comfy.state.outcome = "success"
    again = client.post(f"/api/generation/jobs/{failed['id']}/again")
    assert again.status_code == 200, again.text
    created = again.json()["generation"]
    assert created["id"] != failed["id"] and created["session_id"] == session_id
    assert created["request"]["prompt"] == "海边的柴犬" and created["model"] == "portrait.json"
    assert wait_settled(client, again.json()["job"]["id"], timeout=60) == "succeeded"
    assert len(_records(client, workspace, session_id)) == 2, "失败那一条留着,新的一条接在后面"


def test_工作台画布上跑的_数字人生成_不能照原样再来(connected) -> None:
    client, comfy, workspace, profile_id = connected
    with SessionLocal() as db:
        from app.db.models import GenerationSession

        session = GenerationSession(workspace_id=workspace, owner_user_id=user_id(), title="t", kind="image")
        db.add(session)
        db.flush()
        rows = [GenerationJob(workspace_id=workspace, session_id=session.id, kind="image", provider=VENDOR,
                              provider_profile_id=profile_id, model="portrait.json", request=request, error="x")
                for request in ({"prompt": "", "workbench": True}, {"prompt": "说话", "digital_human_consent": True})]
        db.add_all(rows)
        db.commit()
        ids, session_id = [one.id for one in rows], session.id
    records = {one["id"]: one for one in _records(client, workspace, session_id)}
    for generation_id in ids:
        assert records[generation_id]["repeatable"] is False
        refused = client.post(f"/api/generation/jobs/{generation_id}/again")
        assert refused.status_code == 422 and "不能照原样再来一次" in refused.json()["detail"]
