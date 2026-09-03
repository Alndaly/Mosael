"""内置工作流模板。

模板是可编辑的普通工作流图，不是另一套隐藏执行器。创建时把用户已经选择的默认模型固化到
节点上；没设置默认时保留空值，让画布就绪检查准确指出需要补哪一项，而不是替用户猜供应商。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models import ProviderModel
from app.domain.generation.catalog import known_capabilities_for
from app.domain.provider_defaults import get_row
from app.domain.workflows import WorkflowDomainError
from sqlalchemy.orm import Session

FULL_VIDEO_GENERATION = "full_video_generation"
TRANSCRIPT_VIDEO_CLEANUP = "transcript_video_cleanup"


@dataclass(frozen=True)
class ModelChoice:
    profile_id: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class VideoPlan:
    clip_seconds: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    width: int = 1920
    height: int = 1080
    parameters: dict[str, Any] | None = None


def _default_model(db: Session, capability: str, user_id: str) -> ModelChoice:
    row = get_row(db, capability, user_id)
    model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
    if model is None or not model.enabled or model.profile is None or not model.profile.enabled:
        return ModelChoice()
    return ModelChoice(
        profile_id=model.provider_profile_id,
        provider=model.profile.vendor,
        model=model.model_id,
    )


def _video_plan(choice: ModelChoice) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。"""
    capabilities = known_capabilities_for(choice.provider, choice.model, "video")
    if capabilities is None:
        return VideoPlan(parameters={"duration_seconds": 5})

    keys = set(capabilities.get("parameter_keys") or ())
    durations = [int(value) for value in capabilities.get("duration_seconds") or ()]
    if durations:
        preferred = int(capabilities.get("default_duration_seconds") or 5)
        clip_seconds = preferred if preferred in durations else durations[0]
    else:
        low = int(capabilities.get("min_duration_seconds") or 1)
        high = int(capabilities.get("max_duration_seconds") or max(5, low))
        clip_seconds = max(low, min(int(capabilities.get("default_duration_seconds") or 5), high))

    aspect_ratio = str(capabilities.get("default_aspect_ratio") or "16:9")
    resolution = str(capabilities.get("default_resolution") or "720p")
    parameters: dict[str, Any] = {}
    if "duration_seconds" in keys:
        parameters["duration_seconds"] = clip_seconds
    if "aspect_ratio" in keys:
        parameters["aspect_ratio"] = "{{input.aspect_ratio}}"
    if "resolution" in keys:
        parameters["resolution"] = "{{input.resolution}}"
    if "size" in keys:
        default_size = capabilities.get("default_size")
        if default_size:
            parameters["size"] = str(default_size)
    size_text = str(capabilities.get("default_size") or "").lower().replace("*", "x")
    try:
        size_width, size_height = (int(value) for value in size_text.split("x", 1))
    except (TypeError, ValueError):
        ratio_dimensions = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
        }
        size_width, size_height = ratio_dimensions.get(aspect_ratio, (1920, 1080))
    return VideoPlan(
        clip_seconds=clip_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        width=size_width,
        height=size_height,
        parameters=parameters,
    )


def built_in_template_graph(db: Session, template_id: str, *, user_id: str) -> dict[str, Any]:
    chat = _default_model(db, "chat", user_id)
    if template_id == FULL_VIDEO_GENERATION:
        return full_video_generation_graph(
            chat=chat,
            video=_default_model(db, "video", user_id),
        )
    if template_id == TRANSCRIPT_VIDEO_CLEANUP:
        return transcript_video_cleanup_graph(chat=chat)
    raise WorkflowDomainError(f"未知的内置工作流模板:{template_id}")


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _creative_brief_schema() -> dict[str, Any]:
    fields = {
        "title": {"type": "string", "description": "准确、有记忆点且不过度承诺的视频标题"},
        "core_thesis": {"type": "string", "description": "全片唯一核心主旨，一句话可复述"},
        "audience_takeaway": {"type": "string", "description": "观众看完应理解、感受或采取的行动"},
        "opening_hook": {"type": "string", "description": "前五秒建立问题和观看理由的钩子"},
        "narrative_arc": {"type": "string", "description": "开场、展开、转折、收束的因果弧线"},
        "visual_concept": {"type": "string", "description": "贯穿全片的视觉母题与场景逻辑"},
        "tone": {"type": "string"},
        "factual_boundaries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "不得凭空断言、需要用户复核的事实边界",
        },
    }
    return _object(fields, list(fields))


def _narrative_script_schema() -> dict[str, Any]:
    beat_fields = {
        "beat_number": {"type": "integer", "minimum": 1},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "objective": {"type": "string", "description": "这一段对主旨推进的唯一任务"},
        "narration": {"type": "string", "description": "该时间段的完整口播或对白"},
    }
    fields = {
        "opening_hook": {"type": "string"},
        "narrative_arc": {"type": "string"},
        "full_narration": {"type": "string"},
        "beats": {"type": "array", "minItems": 1, "items": _object(beat_fields, list(beat_fields))},
    }
    return _object(fields, list(fields))


def _visual_bible_schema() -> dict[str, Any]:
    fields = {
        "subject_bible": {"type": "string", "description": "人物或主体跨镜头保持一致的外观与行为"},
        "environment_bible": {"type": "string", "description": "空间、时代、材质与关键道具约束"},
        "camera_language": {"type": "string", "description": "景别、焦段、机位与运镜的统一语法"},
        "lighting_plan": {"type": "string"},
        "color_palette": {"type": "string"},
        "continuity_rules": {"type": "array", "items": {"type": "string"}},
        "global_negative_prompt": {"type": "string"},
    }
    return _object(fields, list(fields))


def _shot_schema(clip_seconds: int) -> dict[str, Any]:
    fields = {
        "shot_number": {"type": "integer", "minimum": 1},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "duration_seconds": {"type": "number", "minimum": clip_seconds, "maximum": clip_seconds},
        "story_beat": {"type": "string", "description": "该镜头推进叙事的唯一任务"},
        "narration": {"type": "string", "description": "该时间段的口播或对白，无则写空字符串"},
        "scene": {"type": "string", "description": "人物、环境、道具与前中后景关系"},
        "shot_size": {"type": "string", "description": "景别及其叙事理由"},
        "camera_angle": {"type": "string", "description": "机位高度、俯仰、视线与镜头焦段"},
        "composition": {"type": "string", "description": "构图、视觉重心、留白与运动方向"},
        "camera_movement": {
            "type": "string",
            "description": "运镜路径、起止构图、速度、加减速和稳定方式",
        },
        "subject_action": {"type": "string", "description": f"主体在 {clip_seconds} 秒内可完成的动作节拍"},
        "lighting": {"type": "string"},
        "color_palette": {"type": "string"},
        "transition_in": {"type": "string"},
        "transition_out": {"type": "string"},
        "sound_design": {"type": "string", "description": "环境声、拟音、音乐节拍与静默点"},
        "continuity_notes": {"type": "string", "description": "人物、服装、空间、光向和运动连续性"},
        "generation_prompt": {
            "type": "string",
            "description": f"可直接交给视频模型的英文提示词，必须包含明确运镜与 {clip_seconds} 秒动作",
        },
        "negative_prompt": {"type": "string"},
    }
    return _object(fields, list(fields))


def _storyboard_schema(clip_seconds: int) -> dict[str, Any]:
    fields = {
        "total_duration_seconds": {"type": "number", "minimum": clip_seconds},
        "timeline_summary": {"type": "string"},
        "continuity_bible": {"type": "string", "description": "所有镜头共享的人物、场景、风格连续性约束"},
        "shots": {"type": "array", "minItems": 1, "items": _shot_schema(clip_seconds)},
    }
    return _object(fields, list(fields))


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
        "cleaned_verbatim": {"type": "string", "description": "按保留内容重排版的逐字稿，不改写原话"},
        "review_notes": {"type": "array", "items": {"type": "string"}},
        "estimated_removed_seconds": {"type": "number", "minimum": 0},
    }
    return _object(fields, list(fields))


def transcript_video_cleanup_graph(*, chat: ModelChoice) -> dict[str, Any]:
    """视频 → 带时间码逐字稿 → 智能诊断 → 多区间波纹裁切 → 整理版导出。"""

    cleanup_system = """你是一名资深口播、访谈与课程剪辑师。你会收到词级或段级时间码逐字稿，
任务是在不改写观点、不改变事实、不打乱时间顺序的前提下，让视频更紧凑、清楚、自然。识别长停顿、
无语义口头禅、重复表达、错误起句后重录、明显跑题和噪声词。只把高置信度且能从时间码精确定位的
问题放入 remove_ranges；结构跳跃、可能有意的停顿、语气表达或任何含义不确定的内容只写进 issues
和 review_notes，不自动删除。范围必须按 src_start 升序、互不重叠、src_end 大于 src_start，并在
素材时长内。删除口头禅时只切独立词；删除停顿时在相邻有效语音两侧各保留约 0.12–0.20 秒自然呼吸。
若重复录制同一句，保留表达最完整自然的一遍。cleaned_verbatim 只能拼接保留的原话，不得润色或
新增内容。只输出符合 JSON Schema 的对象。"""

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": "设置智能整理尺度",
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
            "name": "选择要整理的视频",
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "verbatim_transcript",
            "type": "transcribe_asset",
            "name": "生成带时间码逐字稿",
            "position": {"x": 650, "y": 100},
            "config": {"asset_id": "{{source_video.asset_id}}", "engine": "auto"},
        },
        {
            "id": "cleanup_project",
            "type": "project_sequence_create",
            "name": "建立非破坏性整理副本",
            "position": {"x": 650, "y": 420},
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
            "name": "复制原视频到新时间线",
            "position": {"x": 970, "y": 420},
            "config": {
                "sequence_id": "{{cleanup_project.sequence_id}}",
                "asset_id": "{{source_video.asset_id}}",
                "track_id": "{{cleanup_project.video_track_id}}",
                "start": 0,
                "end": "{{source_video.duration}}",
            },
        },
        {
            "id": "cleanup_plan",
            "type": "llm",
            "name": "诊断杂乱问题并生成整理方案",
            "position": {"x": 1290, "y": 260},
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

下面是按原视频源时间记录的逐字稿 JSON，每段含 start/end，可能含词级 tokens：
{{verbatim_transcript.timed_text}}

请逐项诊断并生成安全的 remove_ranges。所有自动删除范围的总时长不得超过规定比例；无法从逐字稿
确定的画面杂乱、跳剪需求或语义取舍写入 review_notes，不得猜测时间范围。""",
                "response_format": "json_schema",
                "json_schema_name": "transcript_video_cleanup_plan",
                "json_schema": _cleanup_schema(),
                "json_schema_strict": "true",
                "temperature": 0.15,
                "max_tokens": 10000,
            },
        },
        {
            "id": "apply_cleanup",
            "type": "timeline_cut_ranges",
            "name": "按逐字稿批量波纹整理",
            "position": {"x": 1620, "y": 260},
            "config": {
                "sequence_id": "{{cleanup_project.sequence_id}}",
                "clip_id": "{{source_on_timeline.clip_id}}",
                "ranges": "{{cleanup_plan.json.remove_ranges}}",
                "min_confidence": 0.8,
                "max_removal_ratio": "{{start.max_removal_ratio}}",
            },
        },
        {
            "id": "export_clean_video",
            "type": "export_sequence",
            "name": "导出智能整理版视频",
            "position": {"x": 1950, "y": 260},
            "config": {"sequence_id": "{{cleanup_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": "整理完成通知",
            "position": {"x": 2260, "y": 260},
            "config": {
                "title": "视频逐字稿与智能整理已完成",
                "body": "{{source_video.name}} 已生成逐字稿、问题诊断和非破坏性整理版视频。",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": "交付逐字稿、方案与成片",
            "position": {"x": 2570, "y": 260},
            "config": {
                "values": {
                    "source_asset_id": "{{source_video.asset_id}}",
                    "verbatim_transcript": "{{verbatim_transcript.text}}",
                    "timed_transcript": "{{verbatim_transcript.segments}}",
                    "cleanup_plan": "{{cleanup_plan.json}}",
                    "applied_ranges": "{{apply_cleanup.ranges}}",
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
        {"id": "source_transcript", "source": "source_video", "target": "verbatim_transcript"},
        {"id": "source_project", "source": "source_video", "target": "cleanup_project"},
        {"id": "source_append", "source": "source_video", "target": "source_on_timeline"},
        {"id": "project_append", "source": "cleanup_project", "target": "source_on_timeline"},
        {"id": "transcript_plan", "source": "verbatim_transcript", "target": "cleanup_plan"},
        {"id": "append_plan", "source": "source_on_timeline", "target": "cleanup_plan"},
        {"id": "plan_apply", "source": "cleanup_plan", "target": "apply_cleanup"},
        {"id": "apply_export", "source": "apply_cleanup", "target": "export_clean_video"},
        {"id": "export_notice", "source": "export_clean_video", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return {
        "meta": {"template_id": TRANSCRIPT_VIDEO_CLEANUP, "template_version": 1, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }


def full_video_generation_graph(*, chat: ModelChoice, video: ModelChoice) -> dict[str, Any]:
    """主题 → 主旨 → 并行脚本/视觉开发 → 时间分镜 → 逐镜生成合成 → 导出。"""

    video_plan = _video_plan(video)

    brief_system = """你是资深创意总监和纪录片策划。先把用户给出的主题收敛为全片唯一核心主旨，
建立清晰的受众收益、叙事因果和可执行视觉母题。不要编造未经输入支持的具体数字、引语、人物经历
或研究结论；需要核实的内容写入 factual_boundaries。只输出符合 JSON Schema 的对象。"""

    narrative_system = """你是资深编剧和旁白导演。围绕唯一核心主旨规划完整叙事，不引入创意简报之外
的事实。按目标时长拆成首尾连续的叙事节拍：开头尽快建立观看理由，中段用因果而不是信息堆砌推进，
结尾回收主旨。口播要自然、可说、符合指定语言。只输出符合 JSON Schema 的对象。"""

    visual_system = """你是摄影指导、美术指导和连续性监制。根据创意简报建立可供多个视频片段共享的
视觉圣经，明确主体、环境、光线、色彩、镜头语言与连续性规则。规则必须具体到视频生成模型可以复用，
避免空泛风格词；不得要求画面生成字幕、UI、Logo 或水印。只输出符合 JSON Schema 的对象。"""

    storyboard_system = f"""你是导演、摄影指导、分镜师和视频生成提示词工程师。把创意简报拆成连续的
{video_plan.clip_seconds} 秒镜头。每镜必须给出精确起止时间、口播、景别、机位、构图、主体动作、光线、色彩、声音设计、
连续性和运镜。运镜不得只写“推进/环绕”：必须写明镜头从哪里开始、沿什么路径、以何速度移动、
在哪里结束，以及运动如何服务叙事。所有镜头时间必须首尾相接，不重叠、不留空；首镜建立钩子，
中段逐步升级信息，末镜完成主旨回收。generation_prompt 使用英文，能独立交给视频模型，完整复述
主体、环境、风格、镜头语言、动作节拍、运镜和连续性；主体动作必须能在 {video_plan.clip_seconds} 秒内完成；
画面中不要生成字幕、UI、Logo 或水印。
transition_in/out 是交付给后期查看的剪辑意图；本工作流自动合成阶段按时间顺序硬切。只输出符合
JSON Schema 的对象。"""

    shot_body = {
        "nodes": [
            {
                "id": "generate_clip",
                "type": "ai_generate",
                "name": f"按分镜生成 {video_plan.clip_seconds} 秒视频片段",
                "position": {"x": 80, "y": 140},
                "config": {
                    "provider": video.provider,
                    "model": video.model,
                    "kind": "video",
                    "prompt": "{{loop.item.generation_prompt}}",
                    "negative_prompt": "{{loop.item.negative_prompt}}",
                    "parameters": video_plan.parameters or {},
                },
            },
            {
                "id": "organize_clip",
                "type": "asset_update",
                "name": "归档并命名镜头素材",
                "position": {"x": 390, "y": 140},
                "config": {
                    "asset_ids": "{{generate_clip.asset_id}}",
                    "name": "镜头 {{loop.item.shot_number}}",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "append_clip",
                "type": "timeline_append",
                "name": "按镜头顺序接入时间线",
                "position": {"x": 700, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{generate_clip.asset_id}}",
                    "track_id": "{{input.video_track_id}}",
                    "start": 0,
                    "end": video_plan.clip_seconds,
                },
            },
        ],
        "edges": [
            {"id": "shot_generate_organize", "source": "generate_clip", "target": "organize_clip"},
            {"id": "shot_organize_append", "source": "organize_clip", "target": "append_clip"},
        ],
    }

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": "填写视频主题",
            "position": {"x": 40, "y": 300},
            "config": {
                "params": {
                    "topic": "请把这里改成你的视频主题",
                    "target_duration_seconds": 30,
                    "audience": "对该主题感兴趣的大众观众",
                    "tone": "专业、清晰、克制且有电影感",
                    "language": "简体中文",
                    "aspect_ratio": video_plan.aspect_ratio,
                    "resolution": video_plan.resolution,
                    "width": video_plan.width,
                    "height": video_plan.height,
                    "fps": 30,
                }
            },
        },
        {
            "id": "creative_brief",
            "type": "llm",
            "name": "提炼核心主旨与创意简报",
            "position": {"x": 340, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": brief_system,
                "prompt": """主题：{{start.topic}}
目标时长：{{start.target_duration_seconds}} 秒
目标观众：{{start.audience}}
表达气质：{{start.tone}}
成片语言：{{start.language}}

请形成可直接供导演执行的创意简报。核心主旨只能有一个；若主题过宽，主动选择最有叙事张力且
不需要虚构事实的角度。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_creative_brief",
                "json_schema": _creative_brief_schema(),
                "json_schema_strict": "true",
                "temperature": 0.3,
                "max_tokens": 2400,
            },
        },
        {
            "id": "narrative_script",
            "type": "llm",
            "name": "编写叙事脚本与时间节拍",
            "position": {"x": 680, "y": 80},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": narrative_system,
                "prompt": """创意简报：
{{creative_brief.text}}

目标时长：{{start.target_duration_seconds}} 秒
成片语言：{{start.language}}
请输出完整口播，并把叙事拆成按时间连续的 beats。每个 beat 必须有明确叙事任务。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_narrative_script",
                "json_schema": _narrative_script_schema(),
                "json_schema_strict": "true",
                "temperature": 0.4,
                "max_tokens": 5000,
            },
        },
        {
            "id": "visual_bible",
            "type": "llm",
            "name": "建立视觉圣经与连续性规则",
            "position": {"x": 680, "y": 520},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": visual_system,
                "prompt": """创意简报：
{{creative_brief.text}}

画幅：{{start.aspect_ratio}}；表达气质：{{start.tone}}。
请建立整条视频共享的视觉圣经、摄影语言和跨镜头连续性规则。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_visual_bible",
                "json_schema": _visual_bible_schema(),
                "json_schema_strict": "true",
                "temperature": 0.55,
                "max_tokens": 4000,
            },
        },
        {
            "id": "video_project",
            "type": "project_sequence_create",
            "name": "建立成片项目与时间线",
            "position": {"x": 680, "y": 300},
            "config": {
                "name": "{{creative_brief.json.title}} · 自动成片",
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "storyboard",
            "type": "llm",
            "name": "按时间拆解专业脚本与分镜",
            "position": {"x": 1040, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": storyboard_system,
                "prompt": f"""请把叙事脚本与视觉圣经合并成可直接生成的专业时间分镜。

创意简报：
{{{{creative_brief.text}}}}

叙事脚本与节拍：
{{{{narrative_script.text}}}}

视觉圣经与连续性规则：
{{{{visual_bible.text}}}}

成片目标时长：{{{{start.target_duration_seconds}}}} 秒；画幅：{{{{start.aspect_ratio}}}}；
语言：{{{{start.language}}}}。每个镜头固定 {video_plan.clip_seconds} 秒，镜头数按目标时长除以
{video_plan.clip_seconds}；若不能整除，向不少于目标时长的最近倍数取整。时间码从 0 开始连续编号。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_timed_storyboard",
                "json_schema": _storyboard_schema(video_plan.clip_seconds),
                "json_schema_strict": "true",
                "temperature": 0.65,
                "max_tokens": 10000,
            },
        },
        {
            "id": "generate_and_assemble",
            "type": "loop_foreach",
            "name": "逐镜生成视频并按时间合成",
            "position": {"x": 1400, "y": 300},
            "config": {
                "items": "{{storyboard.json.shots}}",
                "inputs": {
                    "project_id": "{{video_project.project_id}}",
                    "sequence_id": "{{video_project.sequence_id}}",
                    "video_track_id": "{{video_project.video_track_id}}",
                    "aspect_ratio": "{{start.aspect_ratio}}",
                    "resolution": "{{start.resolution}}",
                },
                "body": shot_body,
                "output": "{{generate_clip.asset_id}}",
            },
        },
        {
            "id": "export_final",
            "type": "export_sequence",
            "name": "合成并导出最终视频",
            "position": {"x": 1740, "y": 300},
            "config": {"sequence_id": "{{video_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": "成片完成通知",
            "position": {"x": 2080, "y": 120},
            "config": {
                "title": "视频已生成：{{creative_brief.json.title}}",
                "body": "脚本、分镜、视频片段和最终合成均已完成。最终素材 ID：{{export_final.asset_id}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": "交付完整制作结果",
            "position": {"x": 2080, "y": 480},
            "config": {
                "values": {
                    "title": "{{creative_brief.json.title}}",
                    "core_thesis": "{{creative_brief.json.core_thesis}}",
                    "creative_brief": "{{creative_brief.json}}",
                    "narrative_script": "{{narrative_script.json}}",
                    "visual_bible": "{{visual_bible.json}}",
                    "storyboard": "{{storyboard.json}}",
                    "generated_clip_asset_ids": "{{generate_and_assemble.results}}",
                    "project_id": "{{video_project.project_id}}",
                    "sequence_id": "{{video_project.sequence_id}}",
                    "final_asset_id": "{{export_final.asset_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_brief", "source": "start", "target": "creative_brief"},
        {"id": "brief_narrative", "source": "creative_brief", "target": "narrative_script"},
        {"id": "brief_visual", "source": "creative_brief", "target": "visual_bible"},
        {"id": "brief_project", "source": "creative_brief", "target": "video_project"},
        {"id": "narrative_storyboard", "source": "narrative_script", "target": "storyboard"},
        {"id": "visual_storyboard", "source": "visual_bible", "target": "storyboard"},
        {"id": "storyboard_generate", "source": "storyboard", "target": "generate_and_assemble"},
        {"id": "project_generate", "source": "video_project", "target": "generate_and_assemble"},
        {"id": "generate_export", "source": "generate_and_assemble", "target": "export_final"},
        {"id": "export_notice", "source": "export_final", "target": "done_notice"},
        {"id": "export_output", "source": "export_final", "target": "output"},
    ]
    return {
        "meta": {"template_id": FULL_VIDEO_GENERATION, "template_version": 2, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
