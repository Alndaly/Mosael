"""「从主题到完整视频」每镜多长跟着所选视频模型能出的时长走,而且只有一处说了算。

此前每镜秒数在建图那一刻算成一个数,写死进五个地方:视频那一步的时长、上时间线截到哪、分镜和布景的提示词、
分镜的 JSON Schema、节点名「生成 5 秒镜头」。隔离环境里把视频那一步改成 4 秒(省钱),时间线、分镜照旧按 5 秒;
官网副本和认不出的模型一律 5 秒。模型只给几档固定时长、默认那一档又不在里面时,取的是第一档,而不是最接近的。

现在开始节点上有一格「每镜秒数」(建图时按所选模型取它能出的、最接近默认的那一档),视频时长、时间线、提示词、
Schema 都在运行时引用它;改一格全都跟着变,所选模型出不了那个时长的,运行前就拦(和画幅同一道检查)。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.workflows import templates_models
from app.domain.workflows.templates import ModelChoice, full_video_generation_graph
from app.domain.workflows.templates_models import _video_plan

CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
SEEDREAM = ModelChoice(profile_id="image", provider="bytedance", model="doubao-seedream-4-0-250828")
SEEDANCE = ModelChoice(profile_id="video", provider="bytedance", model="doubao-seedance-2-0-260128")
SHOT = "{{start.shot_seconds}}"


@pytest.mark.parametrize(("capabilities", "expected"), [
    ({"duration_seconds": [4, 6, 8], "default_duration_seconds": 8}, 8),
    ({"duration_seconds": [6, 10]}, 6),
    ({"duration_seconds": [4, 6, 8], "default_duration_seconds": 5}, 4),
    ({"duration_seconds": [8, 10], "default_duration_seconds": 5}, 8),
    ({"duration_seconds": [4, 10], "default_duration_seconds": 9}, 10),
    ({"duration_seconds": [2, 4, 6, 8], "default_duration_seconds": 7}, 6),
    ({"duration_seconds": [], "min_duration_seconds": 6, "max_duration_seconds": 10}, 6),
    ({"duration_seconds": [], "default_duration_seconds": 5, "min_duration_seconds": 4, "max_duration_seconds": 15}, 5),
], ids=["默认那档在里面", "没写默认取最接近5秒", "平手取短的那档", "都比默认长取最近", "最近的不是第一档", "平手取短的那档_不是第一档",
     "区间夹到下限", "区间里的默认"])
def test_每镜秒数取模型能出的_最接近默认的那一档(monkeypatch, capabilities: dict[str, Any], expected: int) -> None:
    monkeypatch.setattr(templates_models, "_capabilities", lambda db, choice, kind: {"parameter_keys": ["duration_seconds"], **capabilities})
    assert _video_plan(None, ModelChoice(profile_id="v", provider="x", model="m")).clip_seconds == expected


def _body(graph: dict[str, Any], loop_id: str, node_id: str) -> dict[str, Any]:
    loop = next(node for node in graph["nodes"] if node["id"] == loop_id)
    return next(node for node in loop["config"]["body"]["nodes"] if node["id"] == node_id)


@pytest.mark.parametrize("video", [SEEDANCE, ModelChoice(), ModelChoice(provider="x", model="my-model")],
                         ids=["seedance", "还没挑模型", "认不出的模型"])
def test_每镜秒数只有开始节点那一格说了算(video: ModelChoice) -> None:
    graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=video)
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["start"]["config"]["params"]["shot_seconds"] == 5

    generate = _body(graph, "generate_shots", "generate_clip")
    assert generate["config"]["parameters"]["duration_seconds"] == "{{input.shot_seconds}}"
    assert not any(char.isdigit() for char in json.dumps(generate["name"], ensure_ascii=False)), generate["name"]
    assert nodes["generate_shots"]["config"]["inputs"]["shot_seconds"] == SHOT
    assert nodes["assemble_timeline"]["config"]["inputs"]["shot_seconds"] == SHOT
    assert _body(graph, "assemble_timeline", "append_clip")["config"]["end"] == "{{input.shot_seconds}}"

    for node_id in ("storyboard", "set_design"):
        text = nodes[node_id]["config"]["system"] + nodes[node_id]["config"]["prompt"]
        assert SHOT in text, node_id
        assert "5 秒" not in text and "{time:5," not in text and "duration:5," not in text, node_id
    shot = nodes["storyboard"]["config"]["json_schema"]["properties"]["shots"]["items"]["properties"]
    assert "maximum" not in shot["duration_seconds"], "Schema 不再写死建图那一刻的秒数"


def test_所选模型出不了那个时长_运行前就拦() -> None:
    """Seedance 2.0 收 4–15 秒:每镜 20 秒的话,在任何一次付费调用之前就说清(和画幅同一道检查)。"""
    from app.core.db import SessionLocal
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import run_preflights
    from tests.util import add_provider, fresh_client, user_id

    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="火山", vendor="bytedance", base_url="", api_key="k",
                               model="doubao-seedance-2-0-260128", capability_ids=["video"], make_default=False)
        db.commit()
        video = ModelChoice(profile_id=profile.id, provider="bytedance", model="doubao-seedance-2-0-260128")
    graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=video)
    with SessionLocal() as db:
        run_preflights(db, graph, user_id(), workspace_id=workspace, params={"shot_seconds": 6})
        with pytest.raises(WorkflowDomainError):
            run_preflights(db, graph, user_id(), workspace_id=workspace, params={"shot_seconds": 20})
