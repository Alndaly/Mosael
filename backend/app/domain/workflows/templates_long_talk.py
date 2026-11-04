"""内置模板「任意时长的数字人」:一篇稿子配成一段音频,切成一段段,人物接着上一段的尾巴往下说,接成一条不切镜头的长片。

一次生成只出几秒,要更长只能分段。和「任意长度的连续视频」不同的是,这里每一段的内容不靠语言模型编,**靠音频定**:

- 段数由配音时长算(`plan`);每一段配到它自己那一截音频,音频里含上一段尾巴那一截,接缝处声音和口型都对得上;
- 每段都把人物照片当参考带上:只靠尾巴接,说久了人会变样;
- 第一段和续写是两条工作流(`opening`、`video`):续写的那条还收上一段的尾巴。

数字人要有授权确认:`consent` 是必填的开始参数,没选不跑。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import FRAME_ASPECTS, ModelChoice

LONG_TALK_VIDEO = "long_talk_video"

#: H3 工作流一段 107 帧、24 帧每秒;尾巴 22 帧。时长写在工作流里,这两个数要和它一致。
SEGMENT_SECONDS = 4.458
TAIL_SECONDS = 0.917


def _speaking_prompt(scene: str) -> str:
    return f"{scene} <Picture 1> speaks to the camera, the lips exactly matching <Audio 1>. One continuous shot, no cut."


def long_talk_video_graph(*, opening: ModelChoice, video: ModelChoice, voice_id: str = "") -> dict[str, Any]:
    width, height = FRAME_ASPECTS["16:9"]
    segment_body = {
        "nodes": [
            {
                "id": "tail", "type": "media_clip",
                "name": {"zh": "取上一段的尾巴", "en": "Take the tail of the previous segment"},
                "position": {"x": 80, "y": 60},
                "config": {"asset_id": "{{loop.previous}}", "last_seconds": "{{input.overlap_seconds}}"},
            },
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
                    "source_assets": [
                        "{{tail.asset_id}}:first_clip",
                        "{{input.face_asset_id}}:reference_image",
                        "{{voice.asset_id}}:driving_audio",
                    ],
                    "consent": "{{input.consent}}",
                },
            },
        ],
        "edges": [
            {"id": "tail_extend", "source": "tail", "target": "extend"},
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
                "config": {"sequence_id": "{{input.sequence_id}}", "asset_id": "{{loop.item}}", "start": "{{input.overlap_seconds}}"},
            },
        ],
        "edges": [],
    }
    graph: dict[str, Any] = {
        "meta": {"template_id": LONG_TALK_VIDEO, "template_version": 1, "source": "official"},
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
                        "segment_seconds": SEGMENT_SECONDS,
                        "overlap_seconds": TAIL_SECONDS,
                    },
                    "required_params": ["script", "face_asset_id", "voice_id", "consent"],
                    "param_options": {"consent": [{"value": "yes", "label": "已取得授权 / Consent obtained"}]},
                },
            },
            {
                "id": "speak", "type": "synthesize_speech",
                "name": {"zh": "把稿子配成音频", "en": "Voice the script"},
                "position": {"x": 340, "y": 300},
                "config": {"text": "{{start.script}}", "engine": "builtin:clone", "voice": "{{start.voice_id}}"},
            },
            {
                "id": "voice_info", "type": "asset",
                "name": {"zh": "配音有多长", "en": "How long the voice runs"},
                "position": {"x": 640, "y": 300},
                "config": {"asset_id": "{{speak.asset_id}}"},
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
                },
            },
            {
                "id": "video_project", "type": "project_sequence_create",
                "name": {"zh": "建立项目与时间线", "en": "Create the project and timeline"},
                "position": {"x": 940, "y": 60},
                "config": {"name": "数字人", "width": width, "height": height, "fps": 24},
            },
            {
                "id": "voice_open", "type": "media_clip",
                "name": {"zh": "取第一段的配音", "en": "Take the voice for the first segment"},
                "position": {"x": 1240, "y": 300},
                "config": {"asset_id": "{{speak.asset_id}}", "start": 0, "end": "{{plan.opening_seconds}}"},
            },
            {
                "id": "opening", "type": "ai_generate",
                "name": {"zh": "说第一段", "en": "Speak the first segment"},
                "position": {"x": 1540, "y": 300},
                "config": {
                    "provider": opening.provider, "provider_profile_id": opening.profile_id, "model": opening.model, "kind": "video",
                    "prompt": _speaking_prompt("{{start.scene}}"),
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
                        "voice_asset_id": "{{speak.asset_id}}",
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
                "config": {"sequence_id": "{{video_project.sequence_id}}", "asset_id": "{{opening.asset_id}}"},
            },
            {
                "id": "assemble", "type": "loop_foreach",
                "name": {"zh": "把后面每一段接上去", "en": "Add every later segment"},
                "position": {"x": 2740, "y": 300},
                "config": {
                    "items": "{{segments.results}}",
                    "inputs": {"sequence_id": "{{video_project.sequence_id}}", "overlap_seconds": "{{start.overlap_seconds}}"},
                    "body": assemble_body,
                    "output": "{{loop.item}}",
                },
            },
            {
                "id": "export_final", "type": "export_sequence",
                "name": {"zh": "导出成片", "en": "Export the finished video"},
                "position": {"x": 3040, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}"},
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
            {"id": "speak_info", "source": "speak", "target": "voice_info"},
            {"id": "info_plan", "source": "voice_info", "target": "plan"},
            {"id": "plan_project", "source": "plan", "target": "video_project"},
            {"id": "plan_voice", "source": "plan", "target": "voice_open"},
            {"id": "voice_opening", "source": "voice_open", "target": "opening"},
            {"id": "opening_segments", "source": "opening", "target": "segments"},
            {"id": "segments_clear", "source": "segments", "target": "clear_timeline"},
            {"id": "clear_opening", "source": "clear_timeline", "target": "append_opening"},
            {"id": "opening_assemble", "source": "append_opening", "target": "assemble"},
            {"id": "assemble_export", "source": "assemble", "target": "export_final"},
            {"id": "export_output", "source": "export_final", "target": "output"},
        ],
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
