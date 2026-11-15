"""「漫剧单集」:对白推动的剧本,角色的台词由视频模型出片时一起念出来(ADR 0101)。

两步走来的:
- 最早台词只是叠在图生视频上的配音,画里的人不说话也不演(维护者:「更像是动态漫画,不是漫剧」);
- 接着改成先配 TTS、再用说话照片对口型,嘴是动了,可语气是平的(维护者:「后期配音没什么语气语调,跟情境不符」)。
MiniMax H3 这类模型在同一次生成里出画面和原生人声:台词写进这一镜的提示词,语气跟着表演走。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.templates.full_video import (
    DRAMA_EPISODE,
    DRAMA_NARRATIVE_RULE,
    DRAMA_STORYBOARD_RULE,
    full_video_generation_graph,
)
from app.domain.workflows.templates.model_choice import ModelChoice

CHAT = ModelChoice(profile_id="c", provider="openai-compatible", model="chat")
IMAGE = ModelChoice(profile_id="i", provider="plugin:dev.mosael.comfyui", model="keyframe.json")
VIDEO = ModelChoice(profile_id="v", provider="plugin:dev.mosael.comfyui", model="i2v.json")


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def _shots(graph: dict[str, Any]) -> dict[str, Any]:
    return _node(graph, "generate_shots")["config"]["body"]


def _assemble(graph: dict[str, Any]) -> dict[str, Any]:
    return _node(graph, "assemble_timeline")["config"]["body"]


def _drama() -> dict[str, Any]:
    return full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO, drama=True)


def _full() -> dict[str, Any]:
    return full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO)


def _control(body: dict[str, Any]) -> set[tuple[str, str, str | None]]:
    return {(edge["source"], edge["target"], edge.get("source_handle")) for edge in body["edges"]
            if edge.get("kind", "control") != "data"}


def test_漫剧是自己的模板_剧本和分镜按对白推动来写() -> None:
    graph = _drama()
    assert graph["meta"]["template_id"] == DRAMA_EPISODE
    narrative = _node(graph, "narrative_script")["config"]["system"]
    assert "这是一部漫剧" in narrative and "{clip}" not in narrative, "每镜秒数换成了开始节点的引用"
    assert "{{start.shot_seconds}}" in narrative
    assert "漫剧镜头规则" in _node(graph, "storyboard")["config"]["system"]
    assert DRAMA_NARRATIVE_RULE.count("{clip}") == 1
    #: 没台词的镜头要写明没人开口:原生出声的模型不说清楚,会自己编出人声来
    assert "No one speaks." in DRAMA_STORYBOARD_RULE


def test_对白写进这一镜的生成提示词_由视频模型出片时一起念() -> None:
    body = _shots(_drama())
    ids = {node["id"] for node in body["nodes"]}
    assert not {"talk_clip", "is_dialogue"} & ids, "不再走说话照片"
    cue = _node(body, "dialogue_cue")["config"]["template"]
    for part in ("{{loop.item.speaker}}", "{{find_speaker.description}}", "{{loop.item.narration}}", "Only this one line"):
        assert part in cue, part
    assert ("find_speaker", "dialogue_cue", None) in _control(body), "只有角色在说的镜头才有这一句(旁白镜被跳过,引用是空串)"
    assert "{{dialogue_cue.text}}" in _node(body, "generate_clip")["config"]["prompt"]
    assert _control(body) >= {("render_blockout", "generate_clip", None)}, "每一镜都图生视频,对白镜头也是"


def test_角色台词不再另配_旁白照旧用旁白的嗓子() -> None:
    body = _shots(_drama())
    ids = {node["id"] for node in body["nodes"]}
    assert not {"speaker_has_voice", "speak_as_character"} & ids
    edges = _control(body)
    assert ("has_speaker", "has_voice", "false") in edges and ("has_voice", "narrate", "true") in edges


def test_对白镜头的原声是人在说话_不静音也不当环境声_字幕按画面上屏() -> None:
    graph = _drama()
    assemble = _assemble(graph)
    assert _node(assemble, "has_audio")["config"]["left"] == "{{loop.item.narrate.asset_id}}", "只有旁白另配,才静音原声"
    edges = _control(assemble)
    assert ("has_audio", "is_spoken", "false") in edges and ("is_spoken", "mark_ambience", "false") in edges
    assert ("has_audio", "mark_ambience", "false") not in edges, "对白也被标成环境声,说话时配乐不让"
    assert ("append_clip", "caption", None) in edges, "对白镜头没有另配的那一段,字幕挂在画面之后"
    subtitles = _node(graph, "narration_subtitles")["config"]
    assert (subtitles["start_field"], subtitles["end_field"]) == ("append_clip.timeline_start", "append_clip.timeline_end")


def test_不再要数字人授权() -> None:
    start = _node(_drama(), "start")["config"]
    assert "talk_consent" not in start["params"] and start["required_params"] == ["topic"]


def test_从主题到完整视频不受影响() -> None:
    graph = _full()
    body = _shots(graph)
    ids = {node["id"] for node in body["nodes"]}
    assert {"speaker_has_voice", "speak_as_character"} <= ids and "dialogue_cue" not in ids, "解说片照旧谁说就用谁的嗓子配"
    assert "{{dialogue_cue.text}}" not in _node(body, "generate_clip")["config"]["prompt"]
    assert _node(graph, "narration_subtitles")["config"]["start_field"] == "append_narration.timeline_start"


def test_说话照片的表演提示拼进提示词() -> None:
    """「让它说话」那个节点的表演提示(漫剧不再用它,资产库里让一张人像开口照旧用)。"""
    from app.domain.workflows.executors.talking import speaking_prompt

    said = speaking_prompt({"capabilities": {"prompt": "optional"}}, "She frowns, eyes red, voice trembling.")
    assert said.startswith("She frowns, eyes red, voice trembling.") and "follow the audio" in said


def test_布景台要和分镜一样多_少了当场补齐() -> None:
    """模型长输出时会提前收尾:实测分镜 20 镜,布景只搭了 6 镜,到第 7 镜才炸。整片和漫剧同一个布景节点。"""
    for graph in (_drama(), full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO)):
        config = _node(graph, "set_design")["config"]
        assert config["json_match_field"] == "shots"
        assert config["json_match_items"] == "{{storyboard.json.shots}}"


def test_接时间线之前先清空_重做一轮不会把镜头接两遍() -> None:
    """「接到末尾」是追加:从第几轮重做(ADR 0092)时整段接时间线重跑,20 镜又接在原来那 20 镜后面
    (漫剧第 2 场从第 16 镜重做:成片 80 秒变 161 秒)。连续长镜头、长口播两份模板早就先清空。"""
    for graph in (_drama(), full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO)):
        clear = _node(graph, "clear_timeline")
        assert clear["type"] == "timeline_clear"
        #: 精确引用被规范化升成数据边(配置那一格随之清空)。
        assert {("video_project", "sequence_id", "sequence_id")} <= {
            (edge["source"], edge.get("source_output"), edge.get("target_input"))
            for edge in graph["edges"] if edge.get("kind") == "data" and edge["target"] == "clear_timeline"
        }
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"] if edge.get("kind", "control") != "data"}
        assert ("generate_shots", "clear_timeline") in edges and ("clear_timeline", "assemble_timeline") in edges
        assert ("generate_shots", "assemble_timeline") not in edges, "绕过清空直接接,重做时还是接两遍"
