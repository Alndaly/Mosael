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
    ({"target_seconds": 20, "longest_seconds": 15, "overlap_seconds": 2}, 11, [1]),
    ({"target_seconds": 35, "longest_seconds": 30}, 18, [1]),
    ({"target_seconds": 60, "longest_seconds": 15, "overlap_seconds": 2}, 14, [1, 2, 3, 4]),
    ({"target_seconds": 1, "longest_seconds": 15, "shortest_seconds": 2}, 2, []),
    ({"target_seconds": 7, "longest_seconds": 10, "allowed_seconds": "5,10"}, 10, []),
    ({"target_seconds": 25, "longest_seconds": 10, "allowed_seconds": "5,10"}, 10, [1, 2]),
])
def test_算分段(config: dict, segment: int, rounds: list[int]) -> None:
    made = _plan(**config)
    assert (made["segment_seconds"], list(range(1, len(made["rounds"]) + 1)), made["count"]) == (segment, rounds, len(rounds) + 1)


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
    assert _inner(graph, "shot_chain")["config"]["overlap_seconds"] == 2.1
    extend = _inner(graph, "extend_shot")["config"]["body"]["nodes"]
    assert [node["type"] for node in extend] == ["media_clip", "ai_generate"]
    assert extend[1]["config"]["source_assets"] == ["{{tail.asset_id}}:first_clip", "{{loop.item.last_frame}}:last_frame"]
    assert not [one for one in validate_graph(graph) if "一项一项" in one], "内层循环读上一轮,不该拦外层同时跑"


def test_只收首帧的模型_接最后一帧_没有重叠() -> None:
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=SEEDANCE)
    assert _inner(graph, "shot_chain")["config"]["overlap_seconds"] == 0
    extend = _inner(graph, "extend_shot")["config"]["body"]["nodes"]
    assert extend[0]["type"] == "video_frame"
    assert extend[1]["config"]["source_assets"] == ["{{tail.asset_id}}:first_frame", "{{loop.item.last_frame}}:last_frame"]


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


def test_每一段知道自己演哪一截_尾帧落在最后一段() -> None:
    made = _plan(target_seconds=35, longest_seconds=30, overlap_seconds=0, last_frame_asset_id="尾帧")
    assert made["opening_seconds"] == 18 and made["opening_last_frame"] == ""
    assert made["rounds"] == [{"from_seconds": 18, "clip_from": 18, "to_seconds": 35, "seconds": 17, "frames": 0,
                               "last_frame": "尾帧", "beat": "", "previous_scene": 1, "scene": 2}]


def test_语言模型写少了_铺满算好的段数() -> None:
    rounds = _plan(target_seconds=50, longest_seconds=10, overlap_seconds=0, beats=["甲", "乙"])["rounds"]
    assert [one["beat"] for one in rounds] == ["甲", "甲", "乙", "乙"]


def test_一段都没写_也照样拍够() -> None:
    assert len(_plan(target_seconds=50, longest_seconds=10, overlap_seconds=0, beats=[])["rounds"]) == 4


def test_放得下的一镜_尾帧还在这一段() -> None:
    made = _plan(target_seconds=5, longest_seconds=15, last_frame_asset_id="尾帧")
    assert made["opening_last_frame"] == "尾帧" and made["rounds"] == [] and made["opening_seconds"] == 5


def test_续写时重叠的那截不算新戏() -> None:
    rounds = _plan(target_seconds=20, longest_seconds=15, overlap_seconds=2)["rounds"]
    assert [(one["from_seconds"], one["to_seconds"]) for one in rounds] == [(11, 20)]


def test_按帧定长_满段整段帧数_最后一段只要配音那么长() -> None:
    """数字人的潜空间续写:每段 10.125 秒 = 243 帧,上文 39 帧。41.85 秒的配音,最后一段只剩 7.85 秒(含上文)。"""
    made = _plan(target_seconds=41.85, longest_seconds=10.125, allowed_seconds="10.125", overlap_seconds=39 / 24,
                 fps=24, shortest_seconds=124 / 24)
    assert made["opening_frames"] == 243
    assert [one["frames"] for one in made["rounds"]] == [243, 243, 243, 189]
    assert made["rounds"][-1]["seconds"] == pytest.approx(7.85)


def test_按帧定长_最后一段太短时不短于模型训练过的长度() -> None:
    made = _plan(target_seconds=10.125 + 1, longest_seconds=10.125, allowed_seconds="10.125", overlap_seconds=39 / 24,
                 fps=24, shortest_seconds=124 / 24)
    assert made["rounds"][-1]["seconds"] == pytest.approx(1 + 39 / 24)
    assert made["rounds"][-1]["frames"] == 124


def test_不按帧定长的模型_帧数是零() -> None:
    made = _plan(target_seconds=20, longest_seconds=15, overlap_seconds=2)
    assert made["opening_frames"] == 0 and [one["frames"] for one in made["rounds"]] == [0]


def test_整片模板_第一段不接尾帧_后面的段说清只演哪一截() -> None:
    body = _body(full_video_generation_graph(chat=CHAT, image=IMAGE, video=SEEDANCE))
    clip = next(node for node in body["nodes"] if node["id"] == "generate_clip")["config"]
    assert "{{paint_last_frame.asset_id}}:last_frame" not in clip["source_assets"]
    assert "{{shot_chain.opening_last_frame}}:last_frame" in clip["source_assets"]
    assert "{{shot_chain.opening_seconds}}" in clip["prompt"]
    extend = next(node for node in next(node for node in body["nodes"] if node["id"] == "extend_shot")["config"]["body"]["nodes"]
                  if node["id"] == "extend")["config"]
    assert "{{loop.item.from_seconds}}" in extend["prompt"] and "Do not replay" in extend["prompt"]


def test_长口播切成一行放得下的几条_时间按字数分() -> None:
    text = "雨把街面洗得发蓝，他走得不急，像认得这条空路。积水晃一下，远处的暖黄就亮一下。然后，他停住，收伞，抬头。雨声忽然低了。"
    cues = subjobs._short_cues(text, 2.0, 20.0)
    assert len(cues) > 1 and "".join(line for line, _, _ in cues) == text
    assert all(subjobs._text_width(line) <= subjobs.SUBTITLE_LINE_WIDTH for line, _, _ in cues)
    assert cues[0][1] == 2.0 and sum(length for _, _, length in cues) == pytest.approx(20)
    assert cues[-1][1] + cues[-1][2] == pytest.approx(22)


def test_短句不切() -> None:
    assert subjobs._short_cues("雨停了。", 1.0, 2.0) == [("雨停了。", 1.0, 2.0)]


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

    asked: list[dict] = []

    def generate(db, scope, config):
        asked.append(config)
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
    chain["config"].update({"longest_seconds": 4, "overlap_seconds": 1.5, "last_frame_asset_id": "尾帧"})
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
    assert len(made["shot_chain"]["rounds"]) == 2
    assert len(tails) == 2 and made["join_shot"]["count"] == 3
    #: 第一段不接尾帧,最后一段才接;每段的提示词里是真的秒数,不是没展开的引用。
    assert ":last_frame" in asked[0]["source_assets"] and "尾帧:last_frame" not in asked[0]["source_assets"]
    assert "尾帧:last_frame" not in asked[1]["source_assets"] and "尾帧:last_frame" in asked[2]["source_assets"]
    assert "seconds 0 to 4 of the 9-second action" in asked[0]["prompt"]
    assert "seconds 4 to 6.5 of the action" in asked[1]["prompt"] and "seconds 6.5 to 9 of the action" in asked[2]["prompt"]
    with SessionLocal() as db:
        joined = db.get(Asset, made["join_shot"]["asset_id"])
        assert probe_media(resolve_key(joined.file_key))["duration"] == pytest.approx(9, abs=0.3)
