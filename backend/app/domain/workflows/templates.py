"""内置工作流模板。

模板是可编辑的普通工作流图，不是另一套隐藏执行器。创建时把用户已经选择的默认模型固化到
节点上；没设置默认时保留空值，让画布就绪检查准确指出需要补哪一项，而不是替用户猜供应商。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models import ProviderModel, Voice
from app.domain.generation.catalog import known_capabilities_for
from app.domain.generation.resolution import resolve_row
from app.domain.provider_defaults import get_row
from app.domain.provider_models import effective_capabilities
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.normalization import canonicalize_data_bindings
from sqlalchemy import select
from sqlalchemy.orm import Session

FULL_VIDEO_GENERATION = "full_video_generation"
TRANSCRIPT_VIDEO_CLEANUP = "transcript_video_cleanup"
TRANSLATED_DUB = "translated_dub"


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


def _resolved_video_capabilities(db: Session | None, choice: ModelChoice) -> dict[str, Any] | None:
    """这个模型在 video 下的能力描述符;认不出返回 None(**不猜**)。

    点了名连接且有库可查时走逐模型解析 —— 用户自定义的声明(见 generation/resolution.py)
    在这条路上生效。纯静态上下文(官网模板导出、不建库的单元测试)传 ``db=None``,
    退回内置目录;连模型名都没有时是空选择,不是"不认识",同样 None。
    """
    if not choice.model:
        return None
    if db is not None and choice.profile_id:
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_profile_id == choice.profile_id,
                ProviderModel.model_id == choice.model,
            )
        )
        if model is not None:
            resolved = resolve_row(db, model, "video")
            return resolved.capabilities if resolved.capabilities_known else None
    return known_capabilities_for(choice.provider, choice.model, "video")


def _supports_text_to_video(db: Session | None, choice: ModelChoice) -> bool:
    """这个模型能不能只凭一段文字出片。

    认不出来的模型(用户自建、ComfyUI)算**能** —— 落到"不认识"的时候拿窄名单去拦,
    会把本来能用的模型挡在外面(见 known_capabilities_for 的说明)。
    """
    capabilities = _resolved_video_capabilities(db, choice)
    if capabilities is None:
        return bool(choice.model)
    return "text-to-video" in (capabilities.get("modes") or ())


def _text_to_video_model(db: Session, user_id: str) -> ModelChoice:
    """给示范工作流挑一个**能纯文生视频**的模型。

    不能直接用 video 能力的默认模型:图生视频类的模型(seedance-*-image-to-video、
    wan2.7-i2v 这些,内置目录里有十来个)只声明了 image-to-video —— 而这条工作流的
    generate_clip 只给一段提示词,没有首帧可喂。默认模型恰好是其中之一时,生成的示范
    工作流从第一次运行起就是坏的,而报错发生在跑到那一步之后,离"我只是打开了示范模板"
    已经很远了。

    默认模型能文生视频就用它(用户自己的选择优先);不能就在他**已经配好的**模型里挑一个
    能的。一个都没有时留空 —— 节点上的模型格空着,界面会让他去选,那比塞一个必然失败的
    模型进去诚实。
    """
    chosen = _default_model(db, "video", user_id)
    if _supports_text_to_video(db, chosen):
        return chosen
    # 「是不是视频模型」不是一个列 —— 能力是从行上写的、模型名推的、vendor 预设里
    # 依次得出的(见 provider_models.effective_capabilities)。所以只能取出已启用的行
    # 再逐个问,不能在 SQL 里筛。
    from app.domain import provider_models

    rows = provider_models.models_for_capability(db, "video", user_id=user_id)
    for model in rows:
        if model.profile is None or not model.profile.enabled:
            continue
        if "video" not in effective_capabilities(model):
            continue
        candidate = ModelChoice(
            profile_id=model.provider_profile_id,
            provider=model.profile.vendor,
            model=model.model_id,
        )
        if _supports_text_to_video(db, candidate):
            return candidate
    return ModelChoice()


def _video_plan(db: Session | None, choice: ModelChoice) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。"""
    capabilities = _resolved_video_capabilities(db, choice)
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


#: 官方模板的**说明**:叫什么、干什么、分几步、跑之前要备好什么。图由上面那几个函数造,
#: 这里只有给人看的那部分 —— 中英并排写在一处(翻译贴着它翻译的东西,和插件清单同一套)。
#:
#: 此前这份说明有**三套**:应用里的模板卡片(前端 messages.ts 里一串 key)、官网模板页
#: (同步脚本里另写一份)、以及这里的图。三套各写各的,改一处不会让另外两处报错,只会让同一个
#: 模板在三个地方讲三种话。现在应用和官网都读这一份。
TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "full_video_generation",
        "name": {
            "zh": "从主题到完整视频",
            "en": "Topic to finished video"
        },
        "summary": {
            "zh": "输入一个主题，生成创意主旨、脚本、视觉方案与分镜，逐镜生成视频并组装导出。各镜同时生成以节省时间；可选添加旁白，每镜口播对齐到它自己的画面并配上字幕。",
            "en": "Turn a topic into a creative brief, script, visual direction and storyboard, then generate, assemble and export the video. Shots are generated in parallel to save time. Narration is optional; each shot's narration is aligned to its own picture and captioned."
        },
        "requires": {
            "zh": [
                "AI 对话模型",
                "支持文生视频的模型",
                "旁白可选：克隆音色"
            ],
            "en": [
                "Chat model",
                "Text-to-video model",
                "Optional narration: cloned voice"
            ]
        },
        "stages": {
            "zh": [
                "输入主题",
                "脚本与视觉方案",
                "生成分镜",
                "各镜同时生成",
                "按顺序组装并配字幕",
                "导出成片"
            ],
            "en": [
                "Choose a topic",
                "Script and visual direction",
                "Storyboard",
                "Generate shots in parallel",
                "Assemble in order with captions",
                "Export"
            ]
        }
    },
    {
        "id": "transcript_video_cleanup",
        "name": {
            "zh": "口播与访谈智能整理",
            "en": "Transcript-based video cleanup"
        },
        "summary": {
            "zh": "先去除底噪，再将视频转为带时间码的逐字稿，识别停顿、口头禅与重复内容，生成裁切方案和整理版视频。保留原素材。",
            "en": "Remove background hiss, transcribe the video with timestamps, identify pauses, fillers and repetition, then create a cut plan and a cleaned video while preserving the original."
        },
        "requires": {
            "zh": [
                "AI 对话模型",
                "可用的转写引擎",
                "待整理的视频素材"
            ],
            "en": [
                "Chat model",
                "Available transcription engine",
                "Source video"
            ]
        },
        "stages": {
            "zh": [
                "选择视频",
                "去除底噪",
                "生成逐字稿",
                "诊断与裁切方案",
                "波纹裁切",
                "导出整理版"
            ],
            "en": [
                "Choose a video",
                "Remove hiss",
                "Transcribe",
                "Review and plan cuts",
                "Ripple cut",
                "Export"
            ]
        }
    },
    {
        "id": "translated_dub",
        "name": {
            "zh": "视频译配 · 字幕与配音",
            "en": "Translated dubbing with subtitles"
        },
        "summary": {
            "zh": "把一段视频逐句转写、逐句翻译，按原时间码铺上译文字幕，再逐条配音并变速压回原段落长度。原声里的人声拆出去、背景音乐留着；没装人声分离引擎时整轨静音，完成通知里会说明。",
            "en": "Transcribe a video sentence by sentence, translate each line, lay translated subtitles on the original timecodes, then dub each line and time-compress it back into its own slot. The original voice is separated out and the background music kept; without a separation engine the original track is muted, and the completion notice says so."
        },
        "requires": {
            "zh": [
                "可用的转写引擎",
                "翻译：AI 对话模型（节点上可换成 Google 翻译）",
                "一把嗓子：配音库的克隆音色，或某个引擎的现成音色",
                "保住背景音乐：人声分离引擎（可选）",
                "有人说话的视频素材"
            ],
            "en": [
                "Available transcription engine",
                "Translation: a chat model (switchable to Google Translate on the node)",
                "A voice: a cloned voice, or a built-in voice from any engine",
                "To keep the background music: a voice separation engine (optional)",
                "A video with speech"
            ]
        },
        "stages": {
            "zh": [
                "选择视频",
                "生成带时间码逐字稿",
                "逐句翻译",
                "按原时间码铺译文字幕",
                "逐条配音并压回原长度",
                "导出译配成片"
            ],
            "en": [
                "Choose a video",
                "Transcribe with timecodes",
                "Translate line by line",
                "Lay subtitles on the original timecodes",
                "Dub and time-compress",
                "Export"
            ]
        }
    }
]


def built_in_template_graph(
    db: Session, template_id: str, *, user_id: str, workspace_id: str = "", locale: str | None = None
) -> dict[str, Any]:
    """按模板造一张图。**节点名在这一刻定语言** —— 图一落库就是用户的数据(他随时可以改名),
    出口再翻就等于翻用户自己写的字。翻译贴着模板里的节点写(见 core.i18n.pick_text),
    和插件清单同一套。"""
    chat = _default_model(db, "chat", user_id)
    if template_id == FULL_VIDEO_GENERATION:
        return localised_names(locale, full_video_generation_graph(
            chat=chat,
            # 这条工作流只给提示词,所以要的是**能文生视频**的那种,不是"video 的默认模型"。
            video=_text_to_video_model(db, user_id),
            # 音色是工作区的(克隆音色存在工作区名下),所以按工作区取,不按人。
            voice_id=_first_voice_id(db, workspace_id),
            db=db,
        ))
    if template_id == TRANSCRIPT_VIDEO_CLEANUP:
        return localised_names(locale, transcript_video_cleanup_graph(chat=chat))
    if template_id == TRANSLATED_DUB:
        # 音色和整片生成那条一样按工作区取:克隆音色存在工作区名下,不跟人走。
        return localised_names(locale, translated_dub_graph(voice_id=_first_voice_id(db, workspace_id)))
    raise WorkflowDomainError("wfErr_unknownTemplate", params={"id": template_id})


def localised_names(locale: str | None, graph: dict[str, Any]) -> dict[str, Any]:
    """把图里每个节点的名字定成一种语言(循环体/子图里的也算)。

    **只动名字**:config 里的值是数据(提示词、模板串),不是给人看的标签 —— 翻它们等于改这条
    工作流要做的事。
    """
    from app.core.i18n import pick_text

    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and isinstance(node.get("name"), dict):
            node["name"] = pick_text(node["name"], locale)
        body = (node.get("config") or {}).get("body") if isinstance(node, dict) else None
        if isinstance(body, dict):
            localised_names(locale, body)
    return graph


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
        "narration": {
            "type": "string",
            "description": f"该时间段的口播或对白，念出来不超过 {clip_seconds} 秒；无则写空字符串",
        },
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
    """视频 → 降噪 → 带时间码逐字稿 → 智能诊断 → 多区间波纹裁切 → 整理版导出。

    **先降噪再转写。** 口播、访谈最常见的毛病就是底噪(空调、风扇、电流声),它同时拖累两件事:
    转写认错字(整理方案是照着逐字稿切的),以及成片里一直嗡着。降噪用内置引擎 —— 不用装、
    不动背景音乐;以说话为主、噪声杂的素材,可以在节点上换成 deepfilternet。降噪只换声音,
    时间码不变,所以后面按逐字稿切的每一刀仍然落在原来的位置。
    """

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
            "config": {"asset_id": "{{source_video.asset_id}}", "engine": "auto", "strength": "medium"},
        },
        {
            "id": "verbatim_transcript",
            "type": "transcribe_asset",
            "name": {"zh": "生成带时间码逐字稿", "en": "Transcribe with timecodes"},
            "position": {"x": 970, "y": 100},
            "config": {"asset_id": "{{clean_audio.asset_id}}", "engine": "auto"},
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

下面是按原视频源时间记录的紧凑逐字稿 JSON。每段含 start/end/text；tokens 为短数组，列顺序由
顶层 token_columns 声明（默认是 start/end/text）：
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
            "name": {"zh": "按逐字稿批量波纹整理", "en": "Ripple-cut the timeline from the transcript"},
            "position": {"x": 1930, "y": 260},
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
                "body": "{{source_video.name}} 已降噪,并生成逐字稿、问题诊断和非破坏性整理版视频。",
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
        "meta": {"template_id": TRANSCRIPT_VIDEO_CLEANUP, "template_version": 4, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return canonicalize_data_bindings(graph, node_types=NODE_TYPES)


def translated_dub_graph(*, voice_id: str = "") -> dict[str, Any]:
    """视频 → 逐字稿 → 逐句翻译 → 译文字幕 → 变速配音 → 导出。

    **逐句翻译,不是整篇翻译。** 配音要对得上画面,所以每一句必须知道自己是第几秒到第几秒的 ——
    而那个时间码只存在于原始段落里。整篇丢给翻译再切回句子,切点不可能和原来一致(译文的句数
    本来就和原文不一样),于是每一句都会往后错一点,越到后面错得越多。逐句走,时间码是白拿的:
    第 i 条译文配第 i 段的时间,按构造对齐。

    **但「逐句」说的是切分,不是逐个发请求。** 这一步曾经是 loop_foreach 套一个 translate ——
    N 次串行节点调用、每次一个新连接,而免费翻译端点按 IP 限流,串起来正好踩在它的节流上
    (真机上第 1/31 次就 429)。现在是一个 translate_lines 节点:同样按段切,但 8 路并发、
    共用一条会重试的连接,顺序不变。

    **配音靠变速塞回原长度,不是靠裁剪。** 同一句话译成另一种语言,长度天然对不上;裁掉尾巴等于
    把话说一半,留空则对不上口型。变速改的是片段的 speed(渲染时 atempo),无损、可撤销、事后
    还能在检查器里逐条微调 —— 这是 `dub_subtitles` 的 match_duration。
    """
    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "开始译配", "en": "Start the translated dub"},
            "position": {"x": -270, "y": 260},
            # **目标语言和音色留在它们各自的节点上,不提成起始参数。**
            # 提上来看似更"通用",实际是把两个真控件换成一个自由文本框:`start.params` 在节点
            # 表里是无类型的 `{"type": "object"}`,值那一列只能填字符串或引用上游输出 ——
            # 而起始节点没有上游。留在节点上,`target_lang` 有 9 种语言的下拉、音色有
            # 按引擎列出的真正的选择器。
            # 要让"运行时问我一次"成立,缺的是**起始参数能声明类型**这件事,那是引擎级的口子,
            # 不是这条模板能绕过去的。
            "config": {"params": {}},
        },
        {
            "id": "source_video",
            "type": "asset",
            "name": {"zh": "选择要配音的视频", "en": "Pick the video to dub"},
            "position": {"x": 40, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "dub_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立非破坏性配音副本", "en": "Create a non-destructive dubbing copy"},
            "position": {"x": 350, "y": 420},
            "config": {
                "name": "{{source_video.name}} · 译配版",
                "width": "{{source_video.width}}",
                "height": "{{source_video.height}}",
                "fps": "{{source_video.fps}}",
            },
        },
        {
            "id": "video_on_timeline",
            "type": "timeline_append",
            "name": {"zh": "把原视频接到时间线", "en": "Put the source video on the timeline"},
            "position": {"x": 670, "y": 420},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "asset_id": "{{source_video.asset_id}}",
                "track_id": "{{dub_project.video_track_id}}",
                "start": 0,
                "end": "{{source_video.duration}}",
            },
        },
        {
            "id": "verbatim_transcript",
            "type": "transcribe_asset",
            "name": {"zh": "生成带时间码逐字稿", "en": "Transcribe with timecodes"},
            "position": {"x": 350, "y": 120},
            "config": {"asset_id": "{{source_video.asset_id}}", "engine": "auto"},
        },
        {
            "id": "translate_lines",
            "type": "translate_lines",
            "name": {"zh": "逐句翻译成目标语言", "en": "Translate line by line into the target language"},
            "position": {"x": 990, "y": 120},
            "config": {
                # 直接收 segments:节点自己从每段里取 text,不需要模板层写 `{{loop.item.text}}`。
                "texts": "{{verbatim_transcript.segments}}",
                "target_lang": "en",
                # **官方模板不走免费端点。** 它按出口 IP 封禁,而且是持续的 ——
                # 真机上直接请求拿到的是 Google 的 "Sorry..." 拦截页,重试多少次都一样
                # (机房、VPN、代理出口尤其容易中)。一条官方模板不能把成败押在这上面。
                # 这条链路本来就在用用户自己的供应商(转写、配音都是),翻译用同一套不是新的
                # 花费面;而且 LLM 读的是整句,译文比逐词接口好。节点上仍然可以换回 google。
                "engine": "ai",
            },
        },
        {
            "id": "translated_subtitles",
            "type": "generate_subtitles",
            "name": {"zh": "按原时间码铺译文字幕", "en": "Lay the translated subtitles on the original timecodes"},
            "position": {"x": 1310, "y": 260},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "segments": "{{verbatim_transcript.segments}}",
                "texts": "{{translate_lines.texts}}",
                # 只念译文的话就把这里改成 yes、并把下一个节点的 line 改成 last:
                # 屏幕上两行(原文/译文),嘴里只念下面那行。
                "keep_original": "no",
                # 逐字稿的时间是**素材内**的时间;视频接在第几秒由上一步说了算。
                "offset": "{{video_on_timeline.timeline_start}}",
            },
        },
        {
            "id": "dubbing",
            "type": "dub_subtitles",
            "name": {"zh": "逐条配音并压回原段落长度", "en": "Dub each line and fit it back into its slot"},
            "position": {"x": 1630, "y": 260},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "clip_ids": "{{translated_subtitles.clip_ids}}",
                "match_duration": "yes",
                "line": "all",
                # **译配要的是替换,不是叠加。** 闪避把原声压到 30%,而两边都是人声 ——
                # 观众听见的是两个人同时说话,只是一个小声点(真机上报回来的正是这个)。
                #
                # 但整轨静音会把**背景音乐**一起带走 —— 说话声和音乐混在同一条轨上。
                # 所以先拆:人声那半丢掉、背景音留着,配音叠在背景音之上。装了分离引擎才做得到,
                # 没装就退回整轨静音(ADR-0016 决定 4:一个没装的可选引擎不该让流程失败)。
                "original_audio": "separate",
                "engine": "clone",
                "voice": voice_id,
            },
        },
        {
            "id": "export_dubbed_video",
            "type": "export_sequence",
            "name": {"zh": "导出译配成片(字幕烧进画面)", "en": "Export the dubbed video (subtitles burned in)"},
            "position": {"x": 1950, "y": 260},
            "config": {"sequence_id": "{{dub_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "译配完成通知", "en": "Dubbing finished notice"},
            "position": {"x": 2260, "y": 260},
            "config": {
                "title": "视频译配与字幕已完成",
                # 原声那一句**必须说**:选了「分离」却没装分离引擎时,流程会退回整轨静音 ——
                # 背景音乐跟着没了。不说的话,用户要到看成片时才发现。
                "body": "{{source_video.name}} 已生成 {{dubbing.done}} 条配音(失败 {{dubbing.failed}} 条),配音在单独一条轨上,整条删掉即可回到原样。{{dubbing.original_audio_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付逐字稿、译文、字幕与成片", "en": "Hand over the transcript, the translation, the subtitles and the export"},
            "position": {"x": 2570, "y": 260},
            "config": {
                "values": {
                    "source_asset_id": "{{source_video.asset_id}}",
                    "source_language": "{{verbatim_transcript.language}}",
                    "verbatim_transcript": "{{verbatim_transcript.text}}",
                    "translated_lines": "{{translate_lines.texts}}",
                    "subtitle_track_id": "{{translated_subtitles.track_id}}",
                    "subtitle_count": "{{translated_subtitles.count}}",
                    "dub_track_id": "{{dubbing.track_id}}",
                    "original_audio": "{{dubbing.original_audio}}",
                    "dubbed_lines": "{{dubbing.done}}",
                    "failed_lines": "{{dubbing.failed}}",
                    "project_id": "{{dub_project.project_id}}",
                    "sequence_id": "{{dub_project.sequence_id}}",
                    "final_asset_id": "{{export_dubbed_video.asset_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_source", "source": "start", "target": "source_video"},
        {"id": "source_transcript", "source": "source_video", "target": "verbatim_transcript"},
        {"id": "source_project", "source": "source_video", "target": "dub_project"},
        {"id": "project_append", "source": "dub_project", "target": "video_on_timeline"},
        {"id": "source_append", "source": "source_video", "target": "video_on_timeline"},
        {"id": "transcript_translate", "source": "verbatim_transcript", "target": "translate_lines"},
        {"id": "translate_subtitles", "source": "translate_lines", "target": "translated_subtitles"},
        # 字幕要等视频真的落到时间线上才铺 —— 它的落点是 video_on_timeline 算出来的。
        {"id": "append_subtitles", "source": "video_on_timeline", "target": "translated_subtitles"},
        {"id": "subtitles_dub", "source": "translated_subtitles", "target": "dubbing"},
        {"id": "dub_export", "source": "dubbing", "target": "export_dubbed_video"},
        {"id": "export_notice", "source": "export_dubbed_video", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    graph = {
        "meta": {"template_id": TRANSLATED_DUB, "template_version": 2, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return canonicalize_data_bindings(graph, node_types=NODE_TYPES)


def _first_voice_id(db: Session, workspace_id: str) -> str:
    """工作区里第一个可用音色,没有就空串。

    模板不可能替用户猜一个音色,而语音节点的音色是必填的。有就预填、
    没有就留空并整段跳过 —— 得到的是一部默片,而不是一个跑到第一镜就失败的工作流。
    """
    if not workspace_id:
        return ""
    voice = db.scalars(
        select(Voice).where(Voice.workspace_id == workspace_id).order_by(Voice.created_at)
    ).first()
    return voice.id if voice else ""


def full_video_generation_graph(
    *, chat: ModelChoice, video: ModelChoice, voice_id: str = "", db: Session | None = None
) -> dict[str, Any]:
    """主题 → 主旨 → 并行脚本/视觉开发 → 时间分镜 → 各镜并发生成 → 按序上时间线 → 口播字幕 → 导出。

    ``db`` 让视频模型的默认参数能读到用户自定义的参数声明;官网导出等无库上下文留空,
    退回内置目录(见 _resolved_video_capabilities)。
    """

    video_plan = _video_plan(db, video)

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
中段逐步升级信息，末镜完成主旨回收。每镜 narration 念出来不得超过 {video_plan.clip_seconds} 秒：
中文按每秒约 4 字、英文按每秒约 2.5 个词估算，宁短勿长；超出的部分会被加速压进这一镜，
听起来会很赶。generation_prompt 使用英文，能独立交给视频模型，完整复述
主体、环境、风格、镜头语言、动作节拍、运镜和连续性；主体动作必须能在 {video_plan.clip_seconds} 秒内完成；
画面中不要生成字幕、UI、Logo 或水印。
transition_in/out 是交付给后期查看的剪辑意图；本工作流自动合成阶段按时间顺序硬切。只输出符合
JSON Schema 的对象。"""

    # 逐镜的活分两段:**生成**各镜互不依赖,可以同时跑;**上时间线**要按镜头顺序,只能一镜
    # 一镜来。此前两件事在同一个循环里,于是 N 个镜头的视频生成也只能排着队一个一个等 ——
    # 视频生成动辄一两分钟一条,这是整条流程最慢的地方。
    #
    # 口播有两道闸,因为两件事都可能缺:
    # · 没选音色 —— 音色是语音合成的必填项,而模板不可能替用户猜一个。
    #   空着就整段跳过:得到的是默片,而不是一个跑到一半失败的工作流。
    # · 这一镜没有口播 —— 分镜的 schema 明说"无则写空字符串",纯画面镜头是正常的。
    #   空文本交给合成会失败,而那一镜失败会拖垮整轮循环。
    generate_body = {
        "nodes": [
            {
                "id": "generate_clip",
                "type": "ai_generate",
                "name": {
                    "zh": f"按分镜生成 {video_plan.clip_seconds} 秒视频片段",
                    "en": f"Generate the {video_plan.clip_seconds}s clip for this shot",
                },
                "position": {"x": 80, "y": 140},
                "config": {
                    "provider": video.provider,
                    "provider_profile_id": video.profile_id,
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
                "name": {"zh": "归档并命名镜头素材", "en": "File and name the shot's asset"},
                "position": {"x": 390, "y": 140},
                "config": {
                    "asset_ids": "{{generate_clip.asset_id}}",
                    "name": "镜头 {{loop.item.shot_number}}",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "has_voice",
                "type": "condition",
                "name": {"zh": "选了配音音色吗", "en": "Was a voice picked?"},
                "position": {"x": 80, "y": 300},
                "config": {"left": "{{input.voice_id}}", "op": "not_empty"},
            },
            {
                "id": "has_narration",
                "type": "condition",
                "name": {"zh": "这一镜有口播吗", "en": "Does this shot have narration?"},
                "position": {"x": 390, "y": 300},
                "config": {"left": "{{loop.item.narration}}", "op": "not_empty"},
            },
            {
                "id": "narrate",
                "type": "synthesize_speech",
                "name": {"zh": "合成该镜口播", "en": "Synthesise this shot's narration"},
                "position": {"x": 700, "y": 300},
                # 开始节点里填的是配音库音色的 id,所以引擎是克隆;想用引擎音色,改这里的两格。
                "config": {"text": "{{loop.item.narration}}", "engine": "clone", "voice": "{{input.voice_id}}"},
            },
        ],
        "edges": [
            {"id": "shot_generate_organize", "source": "generate_clip", "target": "organize_clip"},
            {"id": "shot_voice_gate_narration", "source": "has_voice", "target": "has_narration", "branch": "true"},
            {"id": "shot_narration_speak", "source": "has_narration", "target": "narrate", "branch": "true"},
        ],
    }
    # 这一段遍历的是上一段的**结果**:每一项是那一镜的全部产物,连同那一镜的分镜本身
    # (`loop.item.loop.item` —— 外面那层 loop 是这一轮,里面那层是生成那一轮)。
    assemble_body = {
        "nodes": [
            {
                "id": "append_clip",
                "type": "timeline_append",
                "name": {"zh": "按镜头顺序接入时间线", "en": "Append this shot to the timeline in order"},
                "position": {"x": 80, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{loop.item.generate_clip.asset_id}}",
                    "track_id": "{{input.video_track_id}}",
                    "start": 0,
                    "end": video_plan.clip_seconds,
                },
            },
            {
                "id": "has_audio",
                "type": "condition",
                "name": {"zh": "这一镜合成了口播吗", "en": "Did this shot get narration?"},
                "position": {"x": 390, "y": 140},
                "config": {"left": "{{loop.item.narrate.asset_id}}", "op": "not_empty"},
            },
            {
                "id": "append_narration",
                "type": "timeline_append",
                "name": {"zh": "把口播对齐到这一镜", "en": "Align the narration to this shot"},
                "position": {"x": 700, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{loop.item.narrate.asset_id}}",
                    "track_id": "{{input.audio_track_id}}",
                    # **放在这一镜画面开始的那一秒**,不是接在上一段口播后面。此前是后者:
                    # 口播长短不一,第 n 段落在前 n−1 段口播时长之和上,越往后和画面错得越多。
                    # 用的是画面片段**实际**落下的位置,不是分镜里写的 start_seconds —— 那是
                    # 模型写的数字,画面按顺序接在前一镜后面,两者不必一致。
                    "at": "{{append_clip.timeline_start}}",
                    # 不裁(硬裁会把话切掉半句),比镜头长就加速塞进去,最多 1.5 倍。
                    # 分镜提示词里已经按语速给了字数上限,这一道是兜底。
                    "max_duration": video_plan.clip_seconds,
                },
            },
            {
                "id": "caption",
                "type": "template",
                "name": {"zh": "这一镜的字幕文本", "en": "This shot's subtitle text"},
                "position": {"x": 1010, "y": 140},
                "config": {"template": "{{loop.item.loop.item.narration}}"},
            },
        ],
        "edges": [
            {"id": "assemble_clip_gate", "source": "append_clip", "target": "has_audio"},
            {"id": "assemble_gate_narration", "source": "has_audio", "target": "append_narration", "branch": "true"},
            {"id": "assemble_narration_caption", "source": "append_narration", "target": "caption"},
        ],
    }

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填写视频主题", "en": "Describe the video you want"},
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
                    # 配音音色。**留空 = 不配音**(成片只有画面),而不是跑到一半失败 ——
                    # 见循环体里那两道闸。工作区里已经有音色时预填第一个,省掉"我明明有音色
                    # 却还要去别处把 id 抄过来"这一步。
                    "voice_id": voice_id,
                }
            },
        },
        {
            "id": "creative_brief",
            "type": "llm",
            "name": {"zh": "提炼核心主旨与创意简报", "en": "Distil the core idea into a creative brief"},
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
            "name": {"zh": "编写叙事脚本与时间节拍", "en": "Write the narrative script and its beats"},
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
            "name": {"zh": "建立视觉圣经与连续性规则", "en": "Build the visual bible and continuity rules"},
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
            "name": {"zh": "建立成片项目与时间线", "en": "Create the project and its timeline"},
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
            "name": {"zh": "按时间拆解专业脚本与分镜", "en": "Break the script into timed shots"},
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
            "id": "generate_shots",
            "type": "loop_foreach",
            "name": {"zh": "各镜同时生成画面与口播", "en": "Generate every shot's picture and narration"},
            "position": {"x": 1400, "y": 300},
            "config": {
                "items": "{{storyboard.json.shots}}",
                "inputs": {
                    "project_id": "{{video_project.project_id}}",
                    "voice_id": "{{start.voice_id}}",
                },
                "body": generate_body,
                # 不写 output:每一项交出那一镜的全部产物(画面、口播)连同分镜本身,
                # 下一段按顺序上时间线、配字幕都要用。
                "output": "",
                # 三镜同时:视频供应商大多按账号限并发,再多就是排队或 429。
                "concurrency": 3,
            },
        },
        {
            "id": "assemble_timeline",
            "type": "loop_foreach",
            "name": {"zh": "按镜头顺序接上时间线", "en": "Append the shots to the timeline in order"},
            "position": {"x": 1720, "y": 300},
            "config": {
                "items": "{{generate_shots.results}}",
                "inputs": {
                    "sequence_id": "{{video_project.sequence_id}}",
                    "video_track_id": "{{video_project.video_track_id}}",
                    "audio_track_id": "{{video_project.audio_track_id}}",
                },
                "body": assemble_body,
                "output": "",
                # 一镜接一镜:「接到末尾」的落点取决于前一镜已经接上。
                "concurrency": 1,
            },
        },
        {
            "id": "narration_subtitles",
            "type": "generate_subtitles",
            "name": {"zh": "把口播做成字幕", "en": "Turn the narration into subtitles"},
            "position": {"x": 2040, "y": 300},
            "config": {
                "sequence_id": "{{video_project.sequence_id}}",
                "segments": "{{assemble_timeline.results}}",
                # 每一项是上一段那一轮的产物:起止取口播**实际**落下的位置(可能被加速过),
                # 文本取那一镜的口播。没有口播的镜头起止为空,自动跳过。
                "start_field": "append_narration.timeline_start",
                "end_field": "append_narration.timeline_end",
                "text_field": "caption.text",
                # 整片没有口播(没选音色)时交出 0 条,不让一条已经生成完的片子在这里失败。
                "allow_empty": "yes",
            },
        },
        {
            "id": "export_final",
            "type": "export_sequence",
            "name": {"zh": "合成并导出最终视频", "en": "Compose and export the final video"},
            "position": {"x": 2360, "y": 300},
            "config": {"sequence_id": "{{video_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "成片完成通知", "en": "Video finished notice"},
            "position": {"x": 2680, "y": 120},
            "config": {
                "title": "视频已生成：{{creative_brief.json.title}}",
                "body": "脚本、分镜、视频片段和最终合成均已完成。最终素材 ID：{{export_final.asset_id}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付完整制作结果", "en": "Hand over the finished production"},
            "position": {"x": 2680, "y": 480},
            "config": {
                "values": {
                    "title": "{{creative_brief.json.title}}",
                    "core_thesis": "{{creative_brief.json.core_thesis}}",
                    "creative_brief": "{{creative_brief.json}}",
                    "narrative_script": "{{narrative_script.json}}",
                    "visual_bible": "{{visual_bible.json}}",
                    "storyboard": "{{storyboard.json}}",
                    "shots": "{{generate_shots.results}}",
                    "subtitle_count": "{{narration_subtitles.count}}",
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
        {"id": "storyboard_generate", "source": "storyboard", "target": "generate_shots"},
        {"id": "project_generate", "source": "video_project", "target": "generate_shots"},
        {"id": "generate_assemble", "source": "generate_shots", "target": "assemble_timeline"},
        {"id": "assemble_subtitles", "source": "assemble_timeline", "target": "narration_subtitles"},
        {"id": "subtitles_export", "source": "narration_subtitles", "target": "export_final"},
        {"id": "export_notice", "source": "export_final", "target": "done_notice"},
        {"id": "export_output", "source": "export_final", "target": "output"},
    ]
    graph = {
        "meta": {"template_id": FULL_VIDEO_GENERATION, "template_version": 5, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return canonicalize_data_bindings(graph, node_types=NODE_TYPES)
