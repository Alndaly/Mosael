"""中间产物不进素材库。

逐句配音一条字幕配一段音频,一千句就是一千份「zh-TW-HsiaoChenNeural · 配音」摊在素材库里 —— 真实的库里 1228 份
素材,其中 985 份是这样的单句片段。它们是配音这道工序的零件:时间线、配音轨要用,人在素材库里找东西时不需要。

现在素材行上记着它是不是中间产物、是哪一种(`assets.intermediate`):素材库、挑素材、智能体的 list_assets 默认不列;
时间线和工序照常按 id 用它;素材页切过去看得到。
"""

from __future__ import annotations

from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.assets.intermediates import DUB_LINE
from app.domain.jobs import create_job, wait_for_idle_jobs
from app.domain.voices.subtitle_dub import start_subtitle_dub
from tests.util import fresh_client, insert_asset


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_素材库默认不列中间产物_切到那一种才看得见() -> None:
    client = fresh_client()
    ws = _workspace(client)
    narration = insert_asset(ws, kind="audio", name="旁白", tags=["口播"])
    still = insert_asset(ws, kind="image", name="封面")
    lines = [insert_asset(ws, kind="audio", name="zh-TW-HsiaoChenNeural · 配音", tags=["配音"], intermediate=DUB_LINE)
             for _ in range(3)]

    library = client.get("/api/assets", params={"workspace_id": ws}).json()
    assert {item["id"] for item in library["items"]} == {narration, still}
    assert library["total"] == 2
    dubbed = client.get("/api/assets", params={"workspace_id": ws, "intermediate": DUB_LINE}).json()
    assert {item["id"] for item in dubbed["items"]} == set(lines)
    assert all(item["intermediate"] == DUB_LINE for item in dubbed["items"])
    assert client.get("/api/assets", params={"workspace_id": ws, "intermediate": "nonsense"}).status_code == 422

    facets = client.get("/api/assets/facets", params={"workspace_id": ws}).json()
    assert facets["total"] == 2 and facets["kinds"] == {"audio": 1, "image": 1}
    assert facets["tags"] == {"口播": 1}, "页签和标签只数素材库里的"
    assert facets["intermediates"] == {DUB_LINE: 3}, "切过去的入口上写着有几份"
    shelf = client.get("/api/assets/facets", params={"workspace_id": ws, "intermediate": DUB_LINE}).json()
    assert shelf["total"] == 3 and shelf["kinds"] == {"audio": 3} and shelf["tags"] == {"配音": 3}


def test_配音片段的卡片上写着念的是哪一句_也搜得到() -> None:
    client = fresh_client()
    ws = _workspace(client)
    insert_asset(ws, kind="audio", name="zh-TW-HsiaoChenNeural · 配音", intermediate=DUB_LINE,
                 media_info={"duration": 2.0, "dub_line": {"text": "Okay, so today we talk about control net", "voice": "v"}})
    insert_asset(ws, kind="audio", name="zh-TW-HsiaoChenNeural · 配音", intermediate=DUB_LINE,
                 media_info={"duration": 1.0, "dub_line": {"text": "points in the initial picture", "voice": "v"}})

    found = client.get("/api/assets", params={"workspace_id": ws, "intermediate": DUB_LINE, "q": "control"}).json()
    assert [item["media_info"]["line_text"] for item in found["items"]] == ["Okay, so today we talk about control net"]


def test_时间线照常用得到中间产物() -> None:
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    line = insert_asset(ws, kind="audio", name="配音", project_id=project, intermediate=DUB_LINE,
                        media_info={"duration": 2.0})
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "audio")
    placed = client.post(f"/api/sequences/{sequence['id']}/clips",
                         json={"track_id": track["id"], "asset_id": line, "timeline_start": 0, "src_in": 0, "src_out": 2})
    assert placed.status_code == 200, placed.text

    assert [one["id"] for one in client.get(f"/api/sequences/{sequence['id']}/assets").json()] == [line]
    assert client.get(f"/api/assets/{line}").json()["intermediate"] == DUB_LINE
    pool = client.get("/api/assets", params={"workspace_id": ws, "project_id": project}).json()
    assert pool["items"] == [], "剪辑台的素材池同样不列它"


def test_逐句配音让每一句的合成都登记成配音片段(monkeypatch) -> None:
    import app.domain.voices.voices as voices_module

    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    track = next(t["id"] for t in seq["tracks"] if t["kind"] == "subtitle")
    seq = client.post(f"/api/sequences/{sid}/subtitles/generate", json={
        "track_id": track, "cues": [{"text": "第一句", "timeline_start": 0, "duration": 2}, {"text": "第二句", "timeline_start": 3, "duration": 2}],
    }).json()
    clip_ids = [c["id"] for c in next(t for t in seq["tracks"] if t["id"] == track)["clips"]]
    asked: list[str] = []

    def fake_synthesis(db, *, text, project_id, created_by, intermediate="", **_synthesis):
        asked.append(intermediate)
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": 2.0},
                      intermediate=intermediate)
        db.add(audio)
        db.flush()
        job.status = "succeeded"
        job.result = {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)
    with SessionLocal() as db:
        start_subtitle_dub(db, sequence_id=sid, clip_ids=clip_ids, match_duration=True, created_by=None,
                           synthesis={"engine": "builtin:volcano", "engine_voice": "a", "workspace_id": ws})
        db.commit()
    assert wait_for_idle_jobs(15)
    assert asked == [DUB_LINE, DUB_LINE], "配出来的每一句都是这次配音的零件"
    assert client.get("/api/assets", params={"workspace_id": ws}).json()["total"] == 0
    assert len(client.get(f"/api/sequences/{sid}/assets").json()) == 2, "配音轨上照样是这两句"


def test_合成按任务上说的登记成哪种中间产物_不说就是素材库里的(monkeypatch) -> None:
    """合成是公共服务:谁要它把产出当零件,谁在排任务时说(`start_synthesis(intermediate=...)`)。
    AI 工作台里念的一段、智能体配的旁白,不说,照旧进素材库。"""
    from app.domain.voices import voices as voices_domain

    def fake_speak(_db, **kwargs):
        out = Path(kwargs["out_dir"]) / "speech.mp3"
        out.write_bytes(b"ID3fake-audio")
        return out

    monkeypatch.setattr(voices_domain, "speak_to_file", fake_speak)
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        part = voices_domain.start_synthesis(db, text="一句", project_id=None, created_by=None, engine="builtin:edge",
                                             engine_voice="v", workspace_id=ws, intermediate=DUB_LINE).id
        whole = voices_domain.start_synthesis(db, text="一段", project_id=None, created_by=None, engine="builtin:edge",
                                              engine_voice="v", workspace_id=ws).id
        db.commit()
    assert wait_for_idle_jobs(15)
    with SessionLocal() as db:
        made = {job_id: db.get(Asset, db.get(Job, job_id).result["asset_id"]) for job_id in (part, whole)}
        assert made[part].intermediate == DUB_LINE
        assert made[whole].intermediate == ""


def test_智能体列素材默认不列中间产物_点名那一种才列() -> None:
    client = fresh_client()
    ws = _workspace(client)
    narration = insert_asset(ws, kind="audio", name="旁白")
    line = insert_asset(ws, kind="audio", name="配音", intermediate=DUB_LINE)

    listed = client.post("/api/agent/tools/list_assets", json={"arguments": {"workspace_id": ws}}).json()["result"]
    assert [one["id"] for one in listed["assets"]] == [narration]
    asked = client.post("/api/agent/tools/list_assets",
                        json={"arguments": {"workspace_id": ws, "intermediate": DUB_LINE}}).json()["result"]
    assert [one["id"] for one in asked["assets"]] == [line]

