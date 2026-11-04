"""一镜比模型一次能出的长时自动接着往下拍(ADR 0092):算分段、逐段续写、接成一份素材,下游还是一镜一份。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain.assets.importer import register_file_asset
from app.domain.assets.joining import join_segments
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors import registry, subjobs
from app.domain.workflows.graph_rules import validate_graph
from app.domain.workflows.templates_full_video import full_video_generation_graph
from app.domain.workflows.templates_models import ModelChoice, video_plan_for
from app.media.paths import resolve_key
from app.media.probe import probe_media
from tests.util import fresh_client

CHAT = ModelChoice("c", "anthropic", "claude")
IMAGE = ModelChoice("i", "bytedance", "doubao-seedream-4-0-250828")
WAN = ModelChoice("a", "alibaba", "wan2.7-i2v")
SEEDANCE = ModelChoice("b", "bytedance", "doubao-seedance-2-0-260128")


def _plan(**config: Any) -> dict:
    return subjobs.chain_plan(None, SimpleNamespace(), config)


@pytest.mark.parametrize("config,segment,rounds", [
    ({"target_seconds": 8, "longest_seconds": 15}, 8, []),
    ({"target_seconds": 15, "longest_seconds": 15}, 15, []),
    ({"target_seconds": 20, "longest_seconds": 15, "overlap_seconds": 2}, 15, [1]),
    ({"target_seconds": 60, "longest_seconds": 15, "overlap_seconds": 2}, 15, [1, 2, 3, 4]),
    ({"target_seconds": 1, "longest_seconds": 15, "shortest_seconds": 2}, 2, []),
    ({"target_seconds": 7, "longest_seconds": 10, "allowed_seconds": "5,10"}, 10, []),
    ({"target_seconds": 25, "longest_seconds": 10, "allowed_seconds": "5,10"}, 10, [1, 2]),
])
def test_算分段(config: dict, segment: int, rounds: list[int]) -> None:
    made = _plan(**config)
    assert (made["segment_seconds"], made["rounds"], made["count"]) == (segment, rounds, len(rounds) + 1)


def test_重叠不比一段短_永远走不完_当场说() -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _plan(target_seconds=30, longest_seconds=2, overlap_seconds=2)
    assert caught.value.key == "wfErr_chainOverlapTooLong"


def _body(graph: dict) -> dict:
    return next(node for node in graph["nodes"] if node["id"] == "generate_shots")["config"]["body"]


def _inner(graph: dict, node_id: str) -> dict:
    return next(node for node in _body(graph)["nodes"] if node["id"] == node_id)


def test_收待续写片段的模型_尾巴接着拍_还能三镜同时跑() -> None:
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=WAN)
    assert _inner(graph, "shot_chain")["config"]["overlap_seconds"] == 2.0
    extend = _inner(graph, "extend_shot")["config"]["body"]["nodes"]
    assert [node["type"] for node in extend] == ["media_clip", "ai_generate"]
    assert extend[1]["config"]["source_assets"] == ["{{tail.asset_id}}:first_clip"]
    assert not [one for one in validate_graph(graph) if "一项一项" in one], "内层循环读上一轮,不该拦外层同时跑"


def test_只收首帧的模型_接最后一帧_没有重叠() -> None:
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=SEEDANCE)
    assert _inner(graph, "shot_chain")["config"]["overlap_seconds"] == 0
    extend = _inner(graph, "extend_shot")["config"]["body"]["nodes"]
    assert extend[0]["type"] == "video_frame"
    assert extend[1]["config"]["source_assets"] == ["{{tail.asset_id}}:first_frame"]


def test_下游还是一镜一份素材() -> None:
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=WAN)
    assemble = next(node for node in graph["nodes"] if node["id"] == "assemble_timeline")["config"]["body"]
    edges = [(edge.get("source_output"), edge.get("target_input")) for edge in assemble["edges"]]
    text = str(assemble) + str(edges)
    assert "join_shot" in text and "generate_clip" not in text


def test_没挑模型时不接_官网副本和原来一样() -> None:
    graph = full_video_generation_graph(chat=ModelChoice(), image=ModelChoice(), video=ModelChoice())
    assert "shot_chain" not in [node["id"] for node in _body(graph)["nodes"]]
    assert not video_plan_for(None, ModelChoice()).chains


def _video(path: Path, *, offset: float, duration: float) -> Path:
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=20",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-vf", f"trim=start={offset}:duration={duration},setpts=PTS-STARTPTS",
                    "-af", f"atrim=start={offset}:duration={duration},asetpts=PTS-STARTPTS", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def _assets(tmp_path: Path, ws: str, *clips: tuple[float, float]) -> list[str]:
    with SessionLocal() as db:
        made = [register_file_asset(db, workspace_id=ws, project_id=None, source_path=_video(tmp_path / f"{index}.mp4", offset=offset, duration=length),
                                    name=f"段{index}", source="generated") for index, (offset, length) in enumerate(clips)]
        db.commit()
        return [one.id for one in made]


def test_真接三段_重叠去掉_来源记着每一段(tmp_path: Path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = _assets(tmp_path, ws, (0, 4), (3, 4), (6, 4))
    with SessionLocal() as db:
        joined = join_segments(db, [db.get(Asset, one) for one in ids], search_seconds=3)
        db.commit()
        info = probe_media(resolve_key(joined.file_key))
        assert info["duration"] == pytest.approx(10, abs=0.2)
        assert [one["asset_id"] for one in joined.derived_from] == ids


def test_只有一段就是它自己(tmp_path: Path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = _assets(tmp_path, ws, (0, 2))
    with SessionLocal() as db:
        asset = db.get(Asset, ids[0])
        assert join_segments(db, [asset], search_seconds=3) is asset


def test_真跑一镜_超长时续写后接成一条(monkeypatch, tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = iter(_assets(tmp_path, ws, (0, 4), (2.5, 4), (5, 4)))
    tails: list[str] = []

    def generate(db, scope, config):
        return {"asset_id": next(ids), "asset_ids": [], "generation_id": "g"}

    def clip(db, scope, config):
        tails.append(config["asset_id"])
        return {"asset_id": "tail", "source_asset_id": config["asset_id"], "start": 0, "end": 1, "duration": 1}

    monkeypatch.setitem(registry._REGISTRY, "ai_generate", generate)
    monkeypatch.setitem(registry._REGISTRY, "media_clip", clip)
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=WAN)
    body = _body(graph)
    keep = {"shot_chain", "generate_clip", "extend_shot", "join_shot"}
    only = {
        "nodes": [node for node in body["nodes"] if node["id"] in keep],
        "edges": [edge for edge in body["edges"] if edge["source"] in keep and edge["target"] in keep],
    }
    chain = next(node for node in only["nodes"] if node["id"] == "shot_chain")
    chain["config"].update({"longest_seconds": 4, "overlap_seconds": 1.5})
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="长镜头", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    loop = {"id": "L", "type": "loop_foreach", "config": {
        "items": [{"generation_prompt": "走"}], "body": only, "concurrency": 1,
        "inputs": {"shot_seconds": 9, "style": "s", "aspect_ratio": "16:9", "resolution": "720P"},
    }}
    context, _ = execute_graph({"nodes": [{"id": "start", "type": "start", "config": {}}, loop],
                                "edges": [{"id": "e", "source": "start", "target": "L"}]}, wf_id=wf_id, params={})
    made = context["L"]["results"][0]
    assert made["shot_chain"]["rounds"] == [1, 2]
    assert len(tails) == 2 and made["join_shot"]["count"] == 3
    with SessionLocal() as db:
        joined = db.get(Asset, made["join_shot"]["asset_id"])
        assert probe_media(resolve_key(joined.file_key))["duration"] == pytest.approx(9, abs=0.3)
