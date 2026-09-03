"""内置工作流模板。

模板是可编辑的普通工作流图，不是另一套隐藏执行器。创建时把用户已经选择的默认模型固化到
节点上；没设置默认时保留空值，让画布就绪检查准确指出需要补哪一项，而不是替用户猜供应商。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProviderModel
from app.domain.generation.catalog import known_capabilities_for
from app.domain.provider_defaults import get_row
from app.domain.workflows import WorkflowDomainError

FULL_VIDEO_GENERATION = "full_video_generation"


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
    if template_id != FULL_VIDEO_GENERATION:
        raise WorkflowDomainError(f"未知的内置工作流模板:{template_id}")
    return full_video_generation_graph(
        chat=_default_model(db, "chat", user_id),
        video=_default_model(db, "video", user_id),
    )


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


def full_video_generation_graph(*, chat: ModelChoice, video: ModelChoice) -> dict[str, Any]:
    """主题 → 核心主旨 → 专业时间分镜 → 逐镜视频 → 时间线合成 → 成片导出。"""

    video_plan = _video_plan(video)

    brief_system = """你是资深创意总监和纪录片策划。先把用户给出的主题收敛为全片唯一核心主旨，
建立清晰的受众收益、叙事因果和可执行视觉母题。不要编造未经输入支持的具体数字、引语、人物经历
或研究结论；需要核实的内容写入 factual_boundaries。只输出符合 JSON Schema 的对象。"""

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
            "position": {"x": 60, "y": 220},
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
            "position": {"x": 360, "y": 220},
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
            "id": "storyboard",
            "type": "llm",
            "name": "按时间拆解专业脚本与分镜",
            "position": {"x": 690, "y": 220},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": storyboard_system,
                "prompt": f"""请把以下创意简报制作成专业拍摄脚本与时间分镜：
{{{{creative_brief.text}}}}

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
            "id": "video_project",
            "type": "project_sequence_create",
            "name": "建立成片项目与时间线",
            "position": {"x": 1020, "y": 220},
            "config": {
                "name": "{{creative_brief.json.title}} · 自动成片",
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "generate_and_assemble",
            "type": "loop_foreach",
            "name": "逐镜生成视频并按时间合成",
            "position": {"x": 1350, "y": 220},
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
            "position": {"x": 1680, "y": 220},
            "config": {"sequence_id": "{{video_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": "成片完成通知",
            "position": {"x": 1990, "y": 220},
            "config": {
                "title": "视频已生成：{{creative_brief.json.title}}",
                "body": "脚本、分镜、视频片段和最终合成均已完成。最终素材 ID：{{export_final.asset_id}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": "交付完整制作结果",
            "position": {"x": 2300, "y": 220},
            "config": {
                "values": {
                    "title": "{{creative_brief.json.title}}",
                    "core_thesis": "{{creative_brief.json.core_thesis}}",
                    "creative_brief": "{{creative_brief.json}}",
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
        {"id": "brief_storyboard", "source": "creative_brief", "target": "storyboard"},
        {"id": "storyboard_project", "source": "storyboard", "target": "video_project"},
        {"id": "project_generate", "source": "video_project", "target": "generate_and_assemble"},
        {"id": "generate_export", "source": "generate_and_assemble", "target": "export_final"},
        {"id": "export_notice", "source": "export_final", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return {"nodes": nodes, "edges": edges}
