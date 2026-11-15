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


DIALOGUE = ModelChoice(profile_id="d", provider="plugin:dev.mosael.comfyui", model="mosael/examples/minimax_h3_dialogue_voice.json")


def _voiced() -> dict[str, Any]:
    return full_video_generation_graph(chat=CHAT, image=IMAGE, video=VIDEO, dialogue=DIALOGUE, drama=True)


def test_给了对白模型_对白镜头用关键帧加角色参考嗓音出片() -> None:
    """只把台词写进提示词时,同一个角色几镜之间嗓音对不上(实测同一个孩子三镜声纹相似度 0.14–0.42);给 H3 一段角色的
    参考嗓音之后同一个孩子两镜 0.84(维护者:「同一角色声音务必一样」)。"""
    from app.domain.workflows.templates.full_video import VOICE_SAMPLE_TEXT

    body = _shots(_voiced())
    assert _node(body, "voice_sample")["config"]["text"] == VOICE_SAMPLE_TEXT
    #: 嗓子取资产库里这个角色的(一整格引用,规范化成数据边)
    assert {("find_speaker", "voice_engine", "engine"), ("find_speaker", "voice_id", "voice")} <= {
        (edge["source"], edge.get("source_output"), edge.get("target_input"))
        for edge in body["edges"] if edge.get("kind") == "data" and edge["target"] == "voice_sample"
    }
    assert "{{loop.item.narration}}" not in VOICE_SAMPLE_TEXT, "参考嗓音每次念同一句,同一个角色的参考才一模一样"
    speak = _node(body, "speak_line")["config"]
    assert speak["model"] == DIALOGUE.model and speak["kind"] == "video"
    assert speak["source_assets"] == ["{{paint_first_frame.asset_id}}:first_frame", "{{voice_sample.asset_id}}:reference_audio"]
    for part in ("<Picture 1>", "<Audio 1>", "{{loop.item.narration}}", "{{loop.item.generation_prompt}}"):
        assert part in speak["prompt"], part
    assert "dialogue_cue" not in {node["id"] for node in body["nodes"]}, "台词已经写在对白模型的提示词里"
    assert "{{dialogue_cue.text}}" not in _node(body, "generate_clip")["config"]["prompt"]


def test_给了对白模型_两支只跑一支_图生视频只由不是对白那个出口激活() -> None:
    """引擎的判法:有路由边时,没有同向数据线陪着的普通控制边照样激活 —— 白模那条不改接,对白镜头两支都跑、下游拼出一串
    两个素材 id(初版就这样失败过)。"""
    body = _shots(_voiced())
    into = {(source, handle) for source, target, handle in _control(body) if target == "generate_clip"}
    assert into == {("is_dialogue", "false")}
    assert {("is_dialogue", "speak_line", "true"), ("render_blockout", "is_dialogue", None),
            ("find_speaker", "voice_sample", None)} <= _control(body)
    organize = _node(body, "organize_clip")
    assert organize["config"]["asset_ids"] == "{{generate_clip.asset_id}}{{speak_line.asset_id}}"
    assert not {edge["source"] for edge in body["edges"]
                if edge["target"] == "organize_clip" and edge.get("kind", "control") != "data"}, "两条入边是都跑了才跑"
    append = _node(_assemble(_voiced()), "append_clip")["config"]
    assert append["asset_id"] == "{{loop.item.generate_clip.asset_id}}{{loop.item.speak_line.asset_id}}"


def test_官网空白副本带对白那一支_模型格空着() -> None:
    blank = ModelChoice()
    body = _shots(full_video_generation_graph(chat=blank, image=blank, video=blank, dialogue=blank, drama=True))
    assert _node(body, "speak_line")["config"]["model"] == ""
