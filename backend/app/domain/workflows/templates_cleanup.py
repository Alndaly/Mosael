"""内置模板「口播精剪」的图:视频 → 降噪 → 带时间码逐字稿 → 智能诊断 → 多区间波纹裁切 → 整理版导出。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import ModelChoice
from app.domain.workflows.templates_schemas import _object


TRANSCRIPT_VIDEO_CLEANUP = "transcript_video_cleanup"


def _cleanup_schema() -> dict[str, Any]:
    issue_fields = {
        "issue_type": {
            "type": "string",
            "enum": ["silence", "filler", "repetition", "false_start", "off_topic", "verbal_noise", "structure"],
        },
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "minimum": 0},
        "excerpt": {"type": "string"},
        "diagnosis": {"type": "string"},
        "recommendation": {"type": "string"},
        "auto_cut": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    range_fields = {
        "src_start": {"type": "number", "minimum": 0},
        "src_end": {"type": "number", "exclusiveMinimum": 0},
        "issue_type": {
            "type": "string",
            "enum": ["silence", "filler", "repetition", "false_start", "off_topic", "verbal_noise"],
        },
        "reason": {"type": "string"},
        "transcript_excerpt": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    fields = {
        "editorial_summary": {"type": "string", "description": "素材问题、整理策略和预期改善"},
        "revised_outline": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": _object(issue_fields, list(issue_fields))},
        "remove_ranges": {"type": "array", "items": _object(range_fields, list(range_fields))},
        "review_notes": {"type": "array", "items": {"type": "string"}},
        "estimated_removed_seconds": {"type": "number", "minimum": 0},
    }
    return _object(fields, list(fields))


def transcript_video_cleanup_graph(*, chat: ModelChoice) -> dict[str, Any]:
    """视频 → 降噪 → 带时间码逐字稿 → 智能诊断 → 多区间波纹裁切 → 整理版导出。

    **先降噪再转写。** 口播、访谈最常见的毛病就是底噪(空调、风扇、电流声),它同时拖累两件事:
    转写认错字(整理方案是照着逐字稿切的),以及成片里一直嗡着。降噪用内置引擎 —— 不用装、
    不动背景音乐;以说话为主、噪声杂的素材,可以在节点上换成 deepfilternet。降噪只换声音,
    时间码不变,所以后面按逐字稿切的每一刀仍然落在原来的位置。
    """

    cleanup_system = """你是一名资深口播、访谈与课程剪辑师。你会收到段落级时间码逐字稿：每段有起止和正文；
段内的长停顿在 pauses 里给出起止，停顿两边几个词的时间在 tokens 里。任务是在不改写观点、不改变事实、
不打乱时间顺序的前提下，让视频更紧凑、清楚、自然。识别长停顿、无语义口头禅、重复表达、错误起句后重录、
明显跑题和噪声词。只把高置信度且能从时间码精确定位的问题放入 remove_ranges：段与段之间的停顿按相邻两段
的起止定位，段内停顿按 pauses 定位，口头禅只在 tokens 给出了它的时间时才切独立词；整句的重复、错误起句、
跑题按整段的起止切。结构跳跃、可能有意的停顿、语气表达、没有时间可定位的口头禅或任何含义不确定的内容只写进
issues 和 review_notes，不自动删除。范围必须按 src_start 升序、互不重叠、src_end 大于 src_start，并在
素材时长内。删除停顿时在相邻有效语音两侧各保留约 0.12–0.20 秒自然呼吸。若重复录制同一句，保留表达最完整
自然的一遍。只输出符合 JSON Schema 的对象。"""

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "设置智能整理尺度", "en": "Set the cleanup thresholds"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "cleanup_style": "自然紧凑，保留真实语气和必要呼吸",
                    "silence_threshold_seconds": 1.0,
                    "filler_policy": "保守：只删除独立且无语义的口头禅",
                    "max_removal_ratio": 0.35,
                }
            },
        },
        {
            "id": "source_video",
            "type": "asset",
            "name": {"zh": "选择要整理的视频", "en": "Pick the video to clean up"},
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "clean_audio",
            "type": "denoise_audio",
            "name": {"zh": "去除底噪(产出新视频,原片不动)", "en": "Remove background noise (a new asset; the source is untouched)"},
            "position": {"x": 650, "y": 260},
            "config": {"asset_id": "{{source_video.asset_id}}", "strength": "medium"},
        },
        {
            "id": "verbatim_transcript",
            "type": "transcribe_asset",
            "name": {"zh": "生成带时间码逐字稿", "en": "Transcribe with timecodes"},
            "position": {"x": 970, "y": 100},
            "config": {"asset_id": "{{clean_audio.asset_id}}"},
        },
        {
            "id": "cleanup_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立非破坏性整理副本", "en": "Create a non-destructive working copy"},
            "position": {"x": 970, "y": 420},
            "config": {
                "name": "{{source_video.name}} · 智能整理",
                "width": "{{source_video.width}}",
                "height": "{{source_video.height}}",
                "fps": "{{source_video.fps}}",
            },
        },
        {
            "id": "source_on_timeline",
            "type": "timeline_append",
            "name": {"zh": "把降噪后的视频放到新时间线", "en": "Put the cleaned video on the new timeline"},
            "position": {"x": 1290, "y": 420},
            "config": {
                "sequence_id": "{{cleanup_project.sequence_id}}",
                "asset_id": "{{clean_audio.asset_id}}",
                "track_id": "{{cleanup_project.video_track_id}}",
                "start": 0,
                "end": "{{source_video.duration}}",
            },
        },
        {
            "id": "cleanup_plan",
            "type": "llm",
            "name": {"zh": "诊断杂乱问题并生成整理方案", "en": "Diagnose the mess and draft a cleanup plan"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": cleanup_system,
                "prompt": """素材名称：{{source_video.name}}
素材时长：{{source_video.duration}} 秒
逐字稿语言：{{verbatim_transcript.language}}
整理风格：{{start.cleanup_style}}
长停顿阈值：{{start.silence_threshold_seconds}} 秒
口头禅策略：{{start.filler_policy}}
最多删除原时长比例：{{start.max_removal_ratio}}

下面是按原视频源时间记录的紧凑逐字稿 JSON。每段含 start/end/text；有段内长停顿的段另有 pauses
（每项是停顿的起止）和 tokens（停顿两边几个词的时间，短数组，列顺序由顶层 token_columns 声明）：
{{verbatim_transcript.timed_text}}

请逐项诊断并生成安全的 remove_ranges。所有自动删除范围的总时长不得超过规定比例；无法从逐字稿
确定的画面杂乱、跳剪需求或语义取舍写入 review_notes，不得猜测时间范围。""",
                "response_format": "json_schema",
                "json_schema_name": "transcript_video_cleanup_plan",
                "json_schema": _cleanup_schema(),
                "json_schema_strict": "true",
                "temperature": 0.15,
                "max_tokens": 16000,
            },
        },
        {
            "id": "apply_cleanup",
            "type": "timeline_cut_ranges",
            "name": {"zh": "按逐字稿批量波纹整理", "en": "Ripple-cut the timeline from the transcript"},
            "position": {"x": 1930, "y": 260},
            "config": {
                "sequence_id": "{{cleanup_project.sequence_id}}",
                "clip_id": "{{source_on_timeline.clip_id}}",
                "ranges": "{{cleanup_plan.json.remove_ranges}}",
                "min_confidence": 0.8,
                #: 超出上限时按置信度删到上限,其余交出来给人复核(skipped_ranges / skipped_note),不再整步失败。
                "max_removal_ratio": "{{start.max_removal_ratio}}",
                #: 整理后的逐字稿在本地由逐字稿减去删除范围拼出来(kept_text),不再让模型全文复述。
                "segments": "{{verbatim_transcript.segments}}",
            },
        },
        {
            "id": "export_clean_video",
            "type": "export_sequence",
            "name": {"zh": "导出智能整理版视频", "en": "Export the cleaned-up video"},
            "position": {"x": 2250, "y": 260},
            "config": {"sequence_id": "{{cleanup_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "整理完成通知", "en": "Cleanup finished notice"},
            "position": {"x": 2570, "y": 260},
            "config": {
                "title": "视频逐字稿与智能整理已完成",
                "body": "{{source_video.name}} 已降噪,并生成逐字稿、问题诊断和非破坏性整理版视频。{{apply_cleanup.skipped_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付逐字稿、方案与成片", "en": "Hand over the transcript, the plan and the export"},
            "position": {"x": 2890, "y": 260},
            "config": {
                "values": {
                    "source_asset_id": "{{source_video.asset_id}}",
                    "denoised_asset_id": "{{clean_audio.asset_id}}",
                    "verbatim_transcript": "{{verbatim_transcript.text}}",
                    "timed_transcript": "{{verbatim_transcript.segments}}",
                    "cleanup_plan": "{{cleanup_plan.json}}",
                    "cleaned_verbatim": "{{apply_cleanup.kept_text}}",
                    "applied_ranges": "{{apply_cleanup.ranges}}",
                    "skipped_ranges": "{{apply_cleanup.skipped_ranges}}",
                    "removed_seconds": "{{apply_cleanup.removed_seconds}}",
                    "project_id": "{{cleanup_project.project_id}}",
                    "sequence_id": "{{cleanup_project.sequence_id}}",
                    "final_asset_id": "{{export_clean_video.asset_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_source", "source": "start", "target": "source_video"},
        {"id": "source_denoise", "source": "source_video", "target": "clean_audio"},
        {"id": "denoise_transcript", "source": "clean_audio", "target": "verbatim_transcript"},
        {"id": "source_project", "source": "source_video", "target": "cleanup_project"},
        {"id": "denoise_append", "source": "clean_audio", "target": "source_on_timeline"},
        {"id": "project_append", "source": "cleanup_project", "target": "source_on_timeline"},
        {"id": "transcript_plan", "source": "verbatim_transcript", "target": "cleanup_plan"},
        {"id": "append_plan", "source": "source_on_timeline", "target": "cleanup_plan"},
        {"id": "plan_apply", "source": "cleanup_plan", "target": "apply_cleanup"},
        {"id": "apply_export", "source": "apply_cleanup", "target": "export_clean_video"},
        {"id": "export_notice", "source": "export_clean_video", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    graph = {
        "meta": {"template_id": TRANSCRIPT_VIDEO_CLEANUP, "template_version": 5, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
