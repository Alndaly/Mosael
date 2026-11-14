"""内置模板「任意时长的数字人」:一篇稿子配成一段音频,切成一段段,人物接着上一段的尾巴往下说,接成一条不切镜头的长片。

一次生成只出几秒,要更长只能分段。和「任意长度的连续视频」不同的是,这里每一段的内容不靠语言模型编,**靠音频定**:

- 配音里的长静音会诱使视频模型换镜头(ADR 0092):配音先压一遍停顿(`tighten`,见 domain/assets/pauses),
  最后一段只生成它配音那么长(`plan` 按帧给长度),不补一截静音画面;
- 段数由压完的配音时长算(`plan`);每一段配到它自己那一截音频,音频里含上一段尾巴那一截,接缝处声音和口型都对得上;
- 每段都把人物照片当参考带上:只靠上文接,说久了人会变样;
- 段与段接在潜空间里:续写读上一段存下的潜空间,不解码、不重新编码,颜色不漂;
- 第一段和续写是两条工作流(`opening`、`video`):续写的那条还读上一段的潜空间。

数字人要有授权确认:`consent` 是必填的开始参数,没选不跑。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates.model_choice import (
    FRAME_ASPECTS, LATENT_CONTEXT_SECONDS, LATENT_FPS, LATENT_LENGTH, LATENT_SEGMENT_SECONDS, LATENT_SHORTEST_SECONDS,
    ModelChoice,
)
from app.media.pauses import DEFAULT_MAX_PAUSE
from app.domain.workflows.templates.upscale import DEFAULT_OUTPUT_RESOLUTION, frame_plan_node, resolution_options, upscale_node

LONG_TALK_VIDEO = "long_talk_video"

def _speaking_prompt(scene: str) -> str:
    """嘴动不动主要看提示词:不把「一直在说」写成最高优先级,就有稿子在念、人却闭着嘴的段落(实测)。"""
    return (f"<Picture 1> is the person in the reference photo; keep the face, hair and clothes exactly. {scene} "
            "Highest priority: whenever the person is on screen the mouth keeps speaking, the lips, jaw and cheeks follow <Audio 1> "
            "syllable by syllable, opening and closing naturally every half second, teeth and the inside of the mouth visible. "
            "Photorealistic documentary footage, real skin with pores, natural micro-expressions, eye blinks, subtle breathing, "
            "natural available light, film grain, no beauty filter, no CGI look. One continuous shot, the camera stays still, no cut.")


def long_talk_video_graph(*, opening: ModelChoice, video: ModelChoice, voice_id: str = "",
                          upscale: ModelChoice | None = None) -> dict[str, Any]:
    """`upscale`:配好的超分工作流(见 templates/upscale)。有它,每段上时间线前超分到开始参数选的清晰度。"""
    width, height = FRAME_ASPECTS["16:9"]
    upscaling = upscale is not None and bool(upscale.model)
    segment_body = {
        "nodes": [
            {
                "id": "voice", "type": "media_clip",
                "name": {"zh": "取这一段的配音", "en": "Take the voice for this segment"},
                "position": {"x": 80, "y": 260},
                "config": {"asset_id": "{{input.voice_asset_id}}", "start": "{{loop.item.clip_from}}", "end": "{{loop.item.to_seconds}}"},
            },
            {
                "id": "extend", "type": "ai_generate",
                "name": {"zh": "接着往下说", "en": "Carry on speaking"},
                "position": {"x": 390, "y": 140},
                "config": {
                    "provider": video.provider, "provider_profile_id": video.profile_id, "model": video.model, "kind": "video",
                    "prompt": _speaking_prompt("{{input.scene}}"),
                    "parameters": {
                        "50.project_folder": "{{input.latent_folder}}", "50.scene_number": "{{loop.item.previous_scene}}",
                        "52.project_folder": "{{input.latent_folder}}", "52.scene_number": "{{loop.item.scene}}",
                        LATENT_LENGTH: "{{loop.item.frames}}",
                    },
                    "source_assets": [
                        "{{input.face_asset_id}}:reference_image",
                        "{{voice.asset_id}}:driving_audio",
                    ],
                    "consent": "{{input.consent}}",
                },
            },
        ],
        "edges": [
            {"id": "voice_extend", "source": "voice", "target": "extend"},
        ],
    }
    #: 按尾巴的长度接,不在画面里找:人一直在说话,差几帧就是声音重叠或缺一截(实测按画面找到 0.79–1.08 秒,尾巴是 0.917)。
    assemble_body = {
        "nodes": [
            {
                "id": "append_segment", "type": "timeline_append",
                "name": {"zh": "接到时间线上", "en": "Add it to the timeline"},
                "position": {"x": 80, "y": 140},
                "config": {"sequence_id": "{{input.sequence_id}}", "start": "{{input.overlap_seconds}}",
                           "asset_id": "{{upscale.asset_id}}" if upscaling else "{{loop.item}}"},
            },
        ],
        "edges": [],
    }
    if upscaling:
        #: 超分只改尺寸不改时长:上文的长度照旧按原片算,配音也照旧对得上。
        assemble_body["nodes"].insert(0, upscale_node("upscale", upscale, asset="{{loop.item}}", width="{{input.frame_width}}",
                                                      height="{{input.frame_height}}", position={"x": 80, "y": 360}))
        assemble_body["edges"].append({"id": "upscale_append", "source": "upscale", "target": "append_segment"})
    graph: dict[str, Any] = {
        "meta": {"template_id": LONG_TALK_VIDEO, "template_version": 5, "source": "official"},
        "nodes": [
            {
                "id": "start", "type": "start",
                "name": {"zh": "开始", "en": "Start"},
                "position": {"x": 40, "y": 300},
                "config": {
                    "params": {
                        "script": "",
                        "face_asset_id": "",
                        "voice_id": voice_id,
                        "scene": "",
                        #: 《互联网信息服务深度合成管理规定》第十四条要求的单独同意:选了才跑。
                        "consent": "",
                        "segment_seconds": LATENT_SEGMENT_SECONDS,
                        "overlap_seconds": LATENT_CONTEXT_SECONDS,
                        **({"aspect_ratio": "16:9", "output_resolution": DEFAULT_OUTPUT_RESOLUTION} if upscaling else {}),
                    },
                    "required_params": ["script", "face_asset_id", "voice_id", "consent"],
                    "param_options": {"consent": [{"value": "yes", "label": "已取得授权 / Consent obtained"}],
                                      **({"output_resolution": resolution_options()} if upscaling else {})},
                },
            },
            {
                "id": "speak", "type": "synthesize_speech",
                "name": {"zh": "把稿子配成音频", "en": "Voice the script"},
                "position": {"x": 340, "y": 300},
                "config": {"text": "{{start.script}}", "engine": "builtin:clone", "voice": "{{start.voice_id}}"},
            },
            {
                #: 配音里的长静音会诱使视频模型换镜头(ADR 0092):硬切都落在静音里。句间停顿压到上限,
                #: 末段那截补齐的静音由 plan 按帧给长度去掉。后面分段、截每段的配音都用压完的这一份。
                "id": "tighten", "type": "tighten_pauses",
                "name": {"zh": "压缩停顿", "en": "Tighten the pauses"},
                "position": {"x": 490, "y": 460},
                "config": {"asset_id": "{{speak.asset_id}}", "max_pause": DEFAULT_MAX_PAUSE},
            },
            {
                "id": "voice_info", "type": "asset",
                "name": {"zh": "配音有多长", "en": "How long the voice runs"},
                "position": {"x": 640, "y": 300},
                "config": {"asset_id": "{{tighten.asset_id}}"},
            },
            {
                "id": "plan", "type": "chain_plan",
                "name": {"zh": "算要几段", "en": "Work out how many segments"},
                "position": {"x": 940, "y": 300},
                "config": {
                    "target_seconds": "{{voice_info.duration}}",
                    "longest_seconds": "{{start.segment_seconds}}",
                    #: 一段的长度写死在工作流里,按这一档算,不拉平。
                    "allowed_seconds": "{{start.segment_seconds}}",
                    "overlap_seconds": "{{start.overlap_seconds}}",
                    #: 每段按帧给长度:配音不够一整段的最后一段不再补一截静音画面(见 LATENT_LENGTH)。
                    "fps": LATENT_FPS,
                    "shortest_seconds": LATENT_SHORTEST_SECONDS,
                },
            },
            {
                "id": "video_project", "type": "project_sequence_create",
                "name": {"zh": "建立项目与时间线", "en": "Create the project and timeline"},
                "position": {"x": 940, "y": 60},
                "config": {"name": "数字人", "fps": 24,
                           **({"width": "{{frame_plan.value.width}}", "height": "{{frame_plan.value.height}}"} if upscaling
                              else {"width": width, "height": height})},
            },
            {
                "id": "voice_open", "type": "media_clip",
                "name": {"zh": "取第一段的配音", "en": "Take the voice for the first segment"},
                "position": {"x": 1240, "y": 300},
                "config": {"asset_id": "{{tighten.asset_id}}", "start": 0, "end": "{{plan.opening_seconds}}"},
            },
            {
                "id": "opening", "type": "ai_generate",
                "name": {"zh": "说第一段", "en": "Speak the first segment"},
                "position": {"x": 1540, "y": 300},
                "config": {
                    "provider": opening.provider, "provider_profile_id": opening.profile_id, "model": opening.model, "kind": "video",
                    "prompt": _speaking_prompt("{{start.scene}}"),
                    "parameters": {"52.project_folder": "mosael/{{video_project.project_id}}", "52.scene_number": 1,
                                   LATENT_LENGTH: "{{plan.opening_frames}}"},
                    "source_assets": ["{{start.face_asset_id}}:reference_image", "{{voice_open.asset_id}}:driving_audio"],
                    "consent": "{{start.consent}}",
                },
            },
            {
                "id": "segments", "type": "loop_foreach",
                "name": {"zh": "一段接一段往下说", "en": "Speak segment after segment"},
                "position": {"x": 1840, "y": 300},
                "config": {
                    "items": "{{plan.rounds}}",
                    "inputs": {
                        "scene": "{{start.scene}}",
                        "consent": "{{start.consent}}",
                        "face_asset_id": "{{start.face_asset_id}}",
                        "voice_asset_id": "{{tighten.asset_id}}",
                        "latent_folder": "mosael/{{video_project.project_id}}",
                        "overlap_seconds": "{{start.overlap_seconds}}",
                    },
                    "body": segment_body,
                    "output": "{{extend.asset_id}}",
                    "previous_initial": "{{opening.asset_id}}",
                },
            },
            {
                "id": "clear_timeline", "type": "timeline_clear",
                "name": {"zh": "清空时间线", "en": "Clear the timeline"},
                "position": {"x": 2140, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}"},
            },
            {
                "id": "append_opening", "type": "timeline_append",
                "name": {"zh": "摆上第一段", "en": "Lay down the first segment"},
                "position": {"x": 2440, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}",
                           "asset_id": "{{upscale_opening.asset_id}}" if upscaling else "{{opening.asset_id}}"},
            },
            {
                "id": "assemble", "type": "loop_foreach",
                "name": {"zh": "把后面每一段接上去", "en": "Add every later segment"},
                "position": {"x": 2740, "y": 300},
                "config": {
                    "items": "{{segments.results}}",
                    "inputs": {"sequence_id": "{{video_project.sequence_id}}", "overlap_seconds": "{{start.overlap_seconds}}",
                               **({"frame_width": "{{frame_plan.value.width}}", "frame_height": "{{frame_plan.value.height}}"}
                                  if upscaling else {})},
                    "body": assemble_body,
                    "output": "{{loop.item}}",
                },
            },
            {
                "id": "export_final", "type": "export_sequence",
                "name": {"zh": "导出成片", "en": "Export the finished video"},
                "position": {"x": 3040, "y": 300},
                #: 默认档走硬件编码,码率低、关键帧密,成片每隔半秒糊一下;生成的片子值得高画质。
                "config": {"sequence_id": "{{video_project.sequence_id}}", "quality": "high"},
            },
            {
                "id": "output", "type": "output",
                "name": {"zh": "交付成片", "en": "Hand over the finished video"},
                "position": {"x": 3340, "y": 300},
                "config": {"values": {"video_asset_id": "{{export_final.asset_id}}", "segments": "{{segments.results}}"}},
            },
        ],
        "edges": [
            {"id": "start_speak", "source": "start", "target": "speak"},
            {"id": "speak_tighten", "source": "speak", "target": "tighten"},
            {"id": "tighten_info", "source": "tighten", "target": "voice_info"},
            {"id": "info_plan", "source": "voice_info", "target": "plan"},
            {"id": "plan_project", "source": "plan", "target": "video_project"},
            {"id": "plan_voice", "source": "plan", "target": "voice_open"},
            {"id": "project_opening", "source": "video_project", "target": "opening"},
            {"id": "voice_opening", "source": "voice_open", "target": "opening"},
            {"id": "opening_segments", "source": "opening", "target": "segments"},
            {"id": "segments_clear", "source": "segments", "target": "clear_timeline"},
            {"id": "clear_opening", "source": "clear_timeline", "target": "append_opening"},
            {"id": "opening_assemble", "source": "append_opening", "target": "assemble"},
            {"id": "assemble_export", "source": "assemble", "target": "export_final"},
            {"id": "export_output", "source": "export_final", "target": "output"},
        ],
    }
    if upscaling:
        graph["nodes"] += [
            frame_plan_node({"x": 640, "y": 60}),
            upscale_node("upscale_opening", upscale, asset="{{opening.asset_id}}", width="{{frame_plan.value.width}}",
                         height="{{frame_plan.value.height}}", position={"x": 2140, "y": 60}),
        ]
        graph["edges"] += [
            {"id": "start_frame_plan", "source": "start", "target": "frame_plan"},
            {"id": "frame_plan_project", "source": "frame_plan", "target": "video_project"},
            {"id": "opening_upscale", "source": "opening", "target": "upscale_opening"},
            {"id": "upscale_append_opening", "source": "upscale_opening", "target": "append_opening"},
        ]
    return normalize_graph(graph, node_types=NODE_TYPES)
