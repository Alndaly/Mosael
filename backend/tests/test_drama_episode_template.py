"""「漫剧单集」:对白推动的剧本,对白镜头用说话照片让关键帧开口(维护者:「更像是动态漫画,不是漫剧」)。

此前台词只是叠在图生视频上的配音:画里的人不说话也不演,看起来是一张会动的插画配着声音。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.templates.full_video import (
    DRAMA_EPISODE,
    DRAMA_NARRATIVE_RULE,
    FULL_VIDEO_GENERATION,
    full_video_generation_graph,
)
from app.domain.workflows.templates.model_choice import ModelChoice

CHAT = ModelChoice(profile_id="c", provider="openai-compatible", model="chat")
IMAGE = ModelChoice(profile_id="i", provider="plugin:dev.mosael.comfyui", model="keyframe.json")
VIDEO = ModelChoice(profile_id="v", provider="plugin:dev.mosael.comfyui", model="i2v.json")
TALK = ModelChoice(profile_id="t", provider="plugin:dev.mosael.comfyui", model="talk.json")


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def _shots(graph: dict[str, Any]) -> dict[str, Any]:
    return _node(graph, "generate_shots")["config"]["body"]


def _drama() -> dict[str, Any]:
    return full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO, talk=TALK, drama=True)


def test_漫剧是自己的模板_剧本和分镜按对白推动来写() -> None:
    graph = _drama()
    assert graph["meta"]["template_id"] == DRAMA_EPISODE
    narrative = _node(graph, "narrative_script")["config"]["system"]
    assert "这是一部漫剧" in narrative and "{clip}" not in narrative, "每镜秒数换成了开始节点的引用"
    assert "{{start.shot_seconds}}" in narrative
    assert "漫剧镜头规则" in _node(graph, "storyboard")["config"]["system"]
    assert DRAMA_NARRATIVE_RULE.count("{clip}") == 1


def test_对白镜头用这一句的配音让关键帧开口_没台词的镜头才图生视频() -> None:
    body = _shots(_drama())
    talk = next(node for node in body["nodes"] if node["id"] == "talk_clip")
    assert talk["type"] == "image_speak"
    #: 开口的是这一镜的首帧(规范化把精确引用升级成数据边)
    assert {"source": "paint_first_frame", "target": "talk_clip", "kind": "data", "source_output": "asset_id",
            "target_input": "asset_id"}.items() <= next(edge for edge in body["edges"] if edge.get("kind") == "data"
                                                         and edge["target"] == "talk_clip").items()
    assert talk["config"]["audio_asset_id"] == "{{speak_as_character.asset_id}}{{narrate.asset_id}}"
    assert talk["config"]["model"] == "t:video:talk.json"
    assert "{{loop.item.generation_prompt}}" in talk["config"]["prompt"], "这一句怎么说(表情、动作)交给说话照片"
    edges = {(edge["source"], edge["target"], edge.get("source_handle")) for edge in body["edges"]}
    assert ("is_dialogue", "talk_clip", "true") in edges
    assert ("is_dialogue", "generate_clip", "false") in edges
    #: 归档和上时间线取两支拼起来的那个(没跑的那支是空串)
    organize = next(node for node in body["nodes"] if node["id"] == "organize_clip")
    assert "{{talk_clip.asset_id}}" in organize["config"]["asset_ids"]
    assert not any(edge["target"] == "organize_clip" for edge in body["edges"]), "两条入边是「都跑了才跑」,归档按引用等"


def test_对白镜头上时间线的是开口的那一段() -> None:
    graph = _drama()
    assemble = next(node for node in graph["nodes"] if node.get("config", {}).get("body", {}).get("nodes")
                    and any(n["id"] == "append_clip" for n in node["config"]["body"]["nodes"]))
    append = next(n for n in assemble["config"]["body"]["nodes"] if n["id"] == "append_clip")
    assert "{{loop.item.talk_clip.asset_id}}" in append["config"]["asset_id"]


def test_用于数字人要跑的人确认() -> None:
    graph = _drama()
    start = _node(graph, "start")["config"]
    assert "talk_consent" in start["required_params"] and start["params"]["talk_consent"] == ""
    assert _node(graph, "generate_shots")["config"]["inputs"]["talk_consent"] == "{{start.talk_consent}}"


def test_从主题到完整视频不受影响() -> None:
    graph = full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO)
    assert graph["meta"]["template_id"] == FULL_VIDEO_GENERATION
    ids = {node["id"] for node in _shots(graph)["nodes"]}
    assert not {"is_dialogue", "talk_clip"} & ids
    assert "漫剧镜头规则" not in _node(graph, "storyboard")["config"]["system"]
    assert "talk_consent" not in _node(graph, "start")["config"]["params"]


def test_官网空白副本也带对白那一支_模型格空着() -> None:
    blank = ModelChoice()
    body = _shots(full_video_generation_graph(chat=blank, image=blank, video=blank, talk=blank, drama=True))
    talk = next(node for node in body["nodes"] if node["id"] == "talk_clip")
    assert talk["config"]["model"] == ""


def test_说话照片的表演提示拼进提示词() -> None:
    from app.domain.workflows.executors.talking import speaking_prompt

    said = speaking_prompt({"capabilities": {"prompt": "optional"}}, "She frowns, eyes red, voice trembling.")
    assert said.startswith("She frowns, eyes red, voice trembling.") and "follow the audio" in said
