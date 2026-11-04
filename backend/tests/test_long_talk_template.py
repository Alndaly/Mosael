"""「任意时长的数字人」:配音定段数,每段配到自己那一截音频、带上尾巴和人物(ADR 0092)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.jobs import wait_for_idle_jobs
from app.domain.workflows.executors import registry
from app.domain.workflows.graph_rules import validate_graph
from app.domain.workflows.templates_long_talk import long_talk_video_graph
from app.domain.workflows.templates_models import ModelChoice
from tests.util import fresh_client

OPEN = ModelChoice("p", "plugin:dev.mosael.comfyui", "minimax_h3_talk_open.json")
CONTINUE = ModelChoice("p", "plugin:dev.mosael.comfyui", "minimax_h3_talk_continue.json")


def test_图是合法的_授权是必填的() -> None:
    graph = long_talk_video_graph(opening=OPEN, video=CONTINUE, voice_id="v")
    assert not validate_graph(graph, require_config=False)
    start = next(node for node in graph["nodes"] if node["id"] == "start")
    assert "consent" in start["config"]["required_params"]


@pytest.fixture
def fake_run(monkeypatch):
    seen: dict[str, Any] = {"generated": [], "clips": [], "starts": []}

    def generate(db, scope, config):
        seen["generated"].append({"model": config["model"], "sources": config["source_assets"], "consent": config["consent"]})
        return {"asset_id": f"seg{len(seen['generated'])}", "asset_ids": [], "generation_id": "g"}

    def clip(db, scope, config):
        seen["clips"].append(config)
        return {"asset_id": f"clip{len(seen['clips'])}", "source_asset_id": config["asset_id"], "start": 0, "end": 1, "duration": 1}

    for node_type, handler in {
        "ai_generate": generate, "media_clip": clip,
        "synthesize_speech": lambda db, scope, config: {"asset_id": "voice", "voice_note": ""},
        "asset": lambda db, scope, config: {"asset_id": "voice", "name": "", "kind": "audio", "duration": 11.0, "width": 0, "height": 0, "fps": 0},
        "project_sequence_create": lambda db, scope, config: {"project_id": "p", "sequence_id": "s", "video_track_id": "v", "audio_track_id": "a", "name": "n"},
        "timeline_clear": lambda db, scope, config: {"removed": 0, "sequence_id": "s"},
        "timeline_append": lambda db, scope, config: seen["starts"].append(config.get("start")) or {"clip_id": "c", "timeline_start": 0, "timeline_end": 1, "duration": 1, "trimmed": 0, "sequence_id": "s"},
        "export_sequence": lambda db, scope, config: {"asset_id": "final"},
    }.items():
        monkeypatch.setitem(registry._REGISTRY, node_type, handler)
    return seen


def test_真跑一遍_每段配到自己那一截音频_带上尾巴和人物(fake_run) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Workflow
    from app.domain.workflows.engine import execute_graph

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="数字人", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = long_talk_video_graph(opening=OPEN, video=CONTINUE, voice_id="v")
    context, _ = execute_graph(graph, wf_id=wf_id, params={"script": "稿子", "face_asset_id": "face", "consent": "yes"})
    wait_for_idle_jobs()
    videos = fake_run["generated"]
    assert [one["model"] for one in videos] == [OPEN.model, CONTINUE.model, CONTINUE.model]
    assert all(one["consent"] == "yes" for one in videos)
    assert all("face:reference_image" in one["sources"] for one in videos), "每段都带人物,说久了才不走样"
    voices = [one for one in fake_run["clips"] if one["asset_id"] == "voice"]
    assert [float(one["start"]) for one in voices] == pytest.approx([0, 3.541, 7.082], abs=0.01)
    assert [float(one["end"]) for one in voices] == pytest.approx([4.458, 7.999, 11.0], abs=0.01)
    assert [float(one) for one in fake_run["starts"][1:]] == [0.917, 0.917], "按尾巴长度接,声音才不重叠"
    assert context["export_final"]["asset_id"] == "final"
