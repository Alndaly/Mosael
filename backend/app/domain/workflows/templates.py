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
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_business import (
    BUSINESS_TEMPLATE_CATALOG,
    FABRIC_LOOKBOOK,
    FOOTAGE_MONTAGE,
    HIGHLIGHT_SHORTS,
    PRODUCT_ON_MODEL,
    PRODUCT_PITCH_SHORT,
    fabric_lookbook_graph,
    footage_montage_graph,
    highlight_shorts_graph,
    product_on_model_graph,
    product_pitch_short_graph,
)
from sqlalchemy import select
from app.ai.providers import FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO
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
    #: 这个视频模型收哪几种参考(见 _video_plan)。决定分镜里每一镜**能选**哪条路:
    #: 首帧(+尾帧)锁构图,或者参考图/参考视频锁人物与运镜。
    keyframes: bool = True
    last_frame: bool = False
    references: bool = False
    reference_video: bool = False

    @property
    def modes(self) -> list[str]:
        return [mode for mode, ok in (("keyframes", self.keyframes), ("references", self.references)) if ok]


@dataclass(frozen=True)
class ImagePlan:
    """图像模型的两种尺寸:关键帧(和成片同画幅)、角色三视图(横向,三个视角并排)。认不出的模型不传尺寸。"""

    frame_sizes: dict[str, str]
    sheet_size: str = ""


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


def _capabilities(db: Session | None, choice: ModelChoice, kind: str) -> dict[str, Any] | None:
    """这个模型在这种生成能力下的描述符;认不出返回 None(**不猜**)。

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
            resolved = resolve_row(db, model, kind)
            return resolved.capabilities if resolved.capabilities_known else None
    return known_capabilities_for(choice.provider, choice.model, kind)


#: 关键帧图要同时参考:白模帧 1 张 + 角色三视图最多 4 张 + 场景设定图最多 3 张 + (尾帧时)首帧 1 张。
REFERENCE_IMAGES_NEEDED = 9


def _can_take_references(db: Session | None, choice: ModelChoice) -> bool:
    """图像模型能不能带着一组参考图出图。认不出的算能(用户自建的、ComfyUI 查不到能力表)。"""
    capabilities = _capabilities(db, choice, "image")
    if capabilities is None:
        return bool(choice.model)
    limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return "image-to-image" in (capabilities.get("modes") or ()) and limit >= REFERENCE_IMAGES_NEEDED


def _can_shoot_from_references(db: Session | None, choice: ModelChoice) -> bool:
    """视频模型能不能从首帧或参考素材出片 —— 这条流程每一镜都给其中之一,从不只给一段文字。"""
    plan = _video_plan(db, choice)
    return bool(choice.model) and (plan.keyframes or plan.references)


def _pick(db: Session, user_id: str, kind: str, usable) -> ModelChoice:
    """默认模型合用就用它(用户自己的选择优先);不合用就在他**已经配好的**模型里挑一个合用的。
    一个都没有时留空 —— 节点上的模型格空着,界面会让他去选,那比塞一个必然失败的进去诚实。"""
    chosen = _default_model(db, kind, user_id)
    if usable(db, chosen):
        return chosen
    from app.domain import provider_models

    for model in provider_models.models_for_capability(db, kind, user_id=user_id):
        if model.profile is None or not model.profile.enabled or kind not in effective_capabilities(model):
            continue
        candidate = ModelChoice(profile_id=model.provider_profile_id, provider=model.profile.vendor, model=model.model_id)
        if usable(db, candidate):
            return candidate
    return ModelChoice()


def _shot_video_model(db: Session, user_id: str) -> ModelChoice:
    return _pick(db, user_id, "video", _can_shoot_from_references)


def _reference_image_model(db: Session, user_id: str) -> ModelChoice:
    return _pick(db, user_id, "image", _can_take_references)


def _image_plan(db: Session | None, choice: ModelChoice) -> ImagePlan:
    """从图像模型的尺寸表里挑:关键帧和成片同画幅,三视图取最宽的横幅。认不出就不传尺寸。"""
    capabilities = _capabilities(db, choice, "image")
    sizes = [str(size).lower().replace("*", "x") for size in (capabilities or {}).get("sizes") or ()]
    minimum = int((capabilities or {}).get("min_size_pixels") or 0)

    def parsed(size: str) -> tuple[int, int]:
        width, height = (int(value) for value in size.split("x", 1))
        return width, height

    def best(ratio: float, *, largest: bool) -> str:
        fitting = [s for s in sizes if abs(parsed(s)[0] / parsed(s)[1] - ratio) < 0.02 and parsed(s)[0] * parsed(s)[1] >= minimum]
        if not fitting:
            return ""
        return sorted(fitting, key=lambda s: parsed(s)[0] * parsed(s)[1], reverse=largest)[0]

    frames = {aspect: best(ratio, largest=False) for aspect, ratio in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0))}
    return ImagePlan(frame_sizes={aspect: size for aspect, size in frames.items() if size}, sheet_size=best(16 / 9, largest=True))


def _video_plan(db: Session | None, choice: ModelChoice) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。"""
    capabilities = _capabilities(db, choice, "video")
    if capabilities is None:
        #: 认不出的模型只按最通用的那条走:首帧生视频。不猜它收参考素材。
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
        keyframes=FIRST_FRAME in keys,
        last_frame=LAST_FRAME in keys,
        references=REFERENCE_IMAGE in keys,
        reference_video=REFERENCE_VIDEO in keys,
    )


#: 官方模板的**说明**:叫什么、干什么、分几步、跑之前要备好什么。图由上面那几个函数造,
#: 这里只有给人看的那部分 —— 中英并排写在一处(翻译贴着它翻译的东西,和插件清单同一套)。
#:
#: 此前这份说明有**三套**:应用里的模板卡片(前端 messages.ts 里一串 key)、官网模板页
#: (同步脚本里另写一份)、以及这里的图。三套各写各的,改一处不会让另外两处报错,只会让同一个
#: 模板在三个地方讲三种话。现在应用和官网都读这一份。
#: 模板库里的卡片。前三条是"无中生有"和"一进一出";后四条(templates_business)是**起点为用户
#: 手里已有的东西** —— 一条长视频、一张商品图。拼在一起是因为模板库只有一份清单。
TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "full_video_generation",
        "name": {
            "zh": "从主题到完整视频",
            "en": "Topic to finished video"
        },
        "summary": {
            "zh": "输入一个主题，生成创意主旨、脚本和视觉圣经，为每个角色画三视图、为每个场景画设定图，按分镜自动搭 3D 白模并摆好每一镜的机位与运镜；再逐镜按白模画首帧（需要时加尾帧）或直接用三视图与白模运镜视频做参考生成视频，按顺序组装、配上口播字幕并导出。",
            "en": "Turn a topic into a creative brief, script and visual bible, draw a turnaround sheet for every character and concept art for every location, auto-build a 3D blockout with each shot's camera position and move, then generate each shot from a first frame (and a last frame where needed) painted on the blockout — or straight from the turnarounds and the blockout camera move — and assemble, caption and export the video."
        },
        "requires": {
            "zh": [
                "AI 对话模型",
                "能带参考图出图的图像模型（如 Seedream 4）",
                "支持首帧或参考素材的视频模型（如 Seedance 2.0）",
                "旁白可选：克隆音色"
            ],
            "en": [
                "Chat model",
                "Image model that takes reference images (e.g. Seedream 4)",
                "Video model that takes a first frame or references (e.g. Seedance 2.0)",
                "Optional narration: cloned voice"
            ]
        },
        "stages": {
            "zh": [
                "输入主题",
                "脚本、角色与视觉圣经",
                "角色三视图与场景设定图",
                "分镜与机位",
                "搭建 3D 白模",
                "逐镜：白模参考 → 首尾帧 → 视频",
                "按顺序组装并配字幕",
                "导出成片"
            ],
            "en": [
                "Choose a topic",
                "Script, characters and visual bible",
                "Character turnarounds and location art",
                "Storyboard and camera set-ups",
                "Build the 3D blockout",
                "Per shot: blockout → keyframes → video",
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
            "zh": "把一段视频逐句转写、逐句翻译，按原时间码铺上译文字幕，再逐条配音并变速压回原段落长度。原声里的人声拆出去、背景音乐留着；开始前需装好人声分离引擎。",
            "en": "Transcribe a video sentence by sentence, translate each line, lay translated subtitles on the original timecodes, then dub each line and time-compress it back into its own slot. The original voice is separated out and the background music kept; a voice separation engine must be ready before the workflow starts."
        },
        "requires": {
            "zh": [
                "可用的转写引擎",
                "翻译：AI 对话模型（节点上可换成 Google 翻译）",
                "一把嗓子：配音库的克隆音色，或某个引擎的现成音色",
                "人声分离引擎（需提前安装）",
                "有人说话的视频素材"
            ],
            "en": [
                "Available transcription engine",
                "Translation: a chat model (switchable to Google Translate on the node)",
                "A voice: a cloned voice, or a built-in voice from any engine",
                "A voice separation engine installed in advance",
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
] + BUSINESS_TEMPLATE_CATALOG


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
            # 三视图和关键帧都要带一组参考图出图;每一镜都给首帧或参考素材,不只给一段文字。
            image=_reference_image_model(db, user_id),
            video=_shot_video_model(db, user_id),
            # 音色是工作区的(克隆音色存在工作区名下),所以按工作区取,不按人。
            voice_id=_first_voice_id(db, workspace_id),
            db=db,
        ))
    if template_id == TRANSCRIPT_VIDEO_CLEANUP:
        return localised_names(locale, transcript_video_cleanup_graph(chat=chat))
    if template_id == TRANSLATED_DUB:
        # 音色和整片生成那条一样按工作区取:克隆音色存在工作区名下,不跟人走。
        return localised_names(locale, translated_dub_graph(voice_id=_first_voice_id(db, workspace_id)))
    if template_id == HIGHLIGHT_SHORTS:
        # 不生成画面,所以只要对话模型;转写引擎由节点自己挑。
        return localised_names(locale, highlight_shorts_graph(chat=chat))
    if template_id == PRODUCT_ON_MODEL:
        return localised_names(locale, product_on_model_graph(
            chat=chat,
            # 商品图要当参考图贯穿每一次出图,所以挑的是"能带参考图出图"的那个,不是随便一个图像模型。
            image=_reference_image_model(db, user_id),
            # 视频是**可选**的一步:没有合适的视频模型就只出静图,而不是让整条模板用不了。
            video=_shot_video_model(db, user_id),
        ))
    if template_id == PRODUCT_PITCH_SHORT:
        return localised_names(locale, product_pitch_short_graph(
            chat=chat,
            image=_reference_image_model(db, user_id),
            voice_id=_first_voice_id(db, workspace_id),
        ))
    if template_id == FOOTAGE_MONTAGE:
        # 不生成画面,所以只要对话模型;音色按工作区取,没有就只出字幕(图里由条件挡掉旁白那两步)。
        return localised_names(locale, footage_montage_graph(chat=chat, voice_id=_first_voice_id(db, workspace_id)))
    if template_id == FABRIC_LOOKBOOK:
        return localised_names(locale, fabric_lookbook_graph(
            chat=chat,
            image=_reference_image_model(db, user_id),
        ))
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


#: 白模里给人物上的颜色。视觉圣经给每个角色分一个,布景照着上色,关键帧提示词照着说"红色人偶是谁"。
BLOCKOUT_COLORS = ["#d9534f", "#4a7fd6", "#5cb85c", "#e0a030"]


def _visual_bible_schema() -> dict[str, Any]:
    character = {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,30}$", "description": "英文小写短 id,如 hero"},
        "name": {"type": "string"},
        "role": {"type": "string", "description": "在故事里是谁"},
        "appearance": {
            "type": "string",
            "description": "英文,交给图像模型画三视图:年龄、脸型发型、服装与配色、体型与身高、标志性道具",
        },
        "height_m": {"type": "number", "minimum": 0.5, "maximum": 2.5},
        "blockout_color": {"type": "string", "enum": BLOCKOUT_COLORS, "description": "白模里这个人偶的颜色,每个角色不同"},
    }
    location = {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,30}$"},
        "name": {"type": "string"},
        "description": {"type": "string", "description": "英文,交给图像模型画场景设定图:空间、时代、材质、关键陈设、光源"},
        "width_m": {"type": "number", "minimum": 2, "maximum": 60},
        "depth_m": {"type": "number", "minimum": 2, "maximum": 60},
        "height_m": {"type": "number", "minimum": 2, "maximum": 20},
    }
    fields = {
        "subject_bible": {"type": "string", "description": "人物或主体跨镜头保持一致的外观与行为"},
        "environment_bible": {"type": "string", "description": "空间、时代、材质与关键道具约束"},
        "camera_language": {"type": "string", "description": "景别、焦段、机位与运镜的统一语法"},
        "lighting_plan": {"type": "string"},
        "color_palette": {"type": "string"},
        "continuity_rules": {"type": "array", "items": {"type": "string"}},
        "global_negative_prompt": {"type": "string"},
        "characters": {
            "type": "array", "maxItems": 4, "items": _object(character, list(character)),
            "description": "出镜的角色(最多 4 个);纯物件/风景的片子可以为空",
        },
        "locations": {
            "type": "array", "maxItems": 3, "items": _object(location, list(location)),
            "description": "全片用到的场景(最多 3 个)",
        },
        "style_prompt": {"type": "string", "description": "英文一句话的全片画风,每张图、每段视频都会带上"},
        "blockout_legend": {
            "type": "string",
            "description": "英文,说明白模里各颜色人偶分别是谁,如 'red mannequin = Lin (class president), blue mannequin = Kai'",
        },
    }
    return _object(fields, list(fields))


SHOT_SIZES = ["extreme wide", "wide", "full", "medium", "medium close-up", "close-up", "extreme close-up"]
CAMERA_ANGLES = ["eye level", "high angle", "low angle", "overhead", "dutch angle"]
CAMERA_MOVES = ["static", "dolly in", "dolly out", "pan", "tilt", "tracking", "orbit", "crane up", "crane down"]


def _shot_schema(plan: VideoPlan) -> dict[str, Any]:
    clip = plan.clip_seconds
    fields: dict[str, Any] = {
        "shot_number": {"type": "integer", "minimum": 1},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "duration_seconds": {"type": "number", "minimum": clip, "maximum": clip},
        "story_beat": {"type": "string", "description": "该镜头推进叙事的唯一任务"},
        "narration": {
            "type": "string",
            "description": f"该时间段的口播或对白，念出来不超过 {clip} 秒；无则写空字符串",
        },
        "location_id": {"type": "string", "description": "视觉圣经里的场景 id"},
        "characters": {"type": "array", "items": {"type": "string"}, "description": "这一镜出镜的角色 id"},
        "blocking": {"type": "string", "description": "人物站位与走位:谁在哪、朝向哪、从哪走到哪(米为单位的相对位置)"},
        "shot_size": {"type": "string", "enum": SHOT_SIZES},
        "camera_angle": {"type": "string", "enum": CAMERA_ANGLES},
        "lens_mm": {"type": "integer", "minimum": 14, "maximum": 200, "description": "等效全画幅焦段"},
        "camera_movement": {"type": "string", "enum": CAMERA_MOVES},
        "camera_path": {"type": "string", "description": "机位从哪里开始、沿什么路径、到哪里结束,起止构图各是什么"},
        "subject_action": {"type": "string", "description": f"主体在 {clip} 秒内可完成的动作节拍"},
        "lighting": {"type": "string"},
        "sound_design": {"type": "string", "description": "环境声、拟音、音乐节拍与静默点"},
        "transition_in": {"type": "string"},
        "transition_out": {"type": "string"},
        "continuity_notes": {"type": "string", "description": "人物、服装、空间、光向和运动连续性"},
        "reference_mode": {
            "type": "string", "enum": plan.modes,
            "description": "这一镜用哪条路出片:keyframes = 先按白模机位画首帧(需要时加尾帧)再生成视频,构图最稳;"
                           "references = 直接把角色三视图、场景设定图和白模运镜视频交给视频模型,适合复杂运镜",
        },
        "first_frame_prompt": {
            "type": "string",
            "description": "英文,这一镜第一帧画面的完整描述(人物、动作、表情、环境、光线、画风),交给图像模型画首帧",
        },
        "generation_prompt": {
            "type": "string",
            "description": f"英文,交给视频模型:主体动作节拍(须能在 {clip} 秒内完成)、表演、环境变化、光影;"
                           "不要写机位参数(会从白模自动补上),不要要求字幕、UI、Logo 或水印",
        },
        "negative_prompt": {"type": "string"},
    }
    if plan.last_frame:
        fields["last_frame_prompt"] = {
            "type": "string",
            "description": "英文,这一镜最后一帧的完整描述;只在结束构图必须精确(大幅运镜、落版、衔接下一镜)时写,否则写空字符串",
        }
    return _object(fields, list(fields))


#: 分镜**最多**能有几镜。这是 schema 上的硬天花板,不是用户那个数 —— 两者分工不同:
#:
#: 用户在 `start.max_shots` 里填的是"我这次想要几镜",走提示词,模型可以据此把成片缩短;
#: 这里是"再怎么样也不能超过"。每一镜都是一次付费的视频生成,而跑之前用户看不到账单 ——
#: 模型一次给出四十镜的后果是四十次扣费,那不该由一句提示词兜着。
#:
#: 故意比默认值宽出一截:两者贴太近的话,模型多给一镜就是整条流程作废(schema 不匹配当场失败),
#: 而那正是我们要避免的失败方式。
MAX_SHOTS_CEILING = 24


def _storyboard_schema(plan: VideoPlan) -> dict[str, Any]:
    fields = {
        "total_duration_seconds": {"type": "number", "minimum": plan.clip_seconds},
        "timeline_summary": {"type": "string"},
        "continuity_bible": {"type": "string", "description": "所有镜头共享的人物、场景、风格连续性约束"},
        "shots": {"type": "array", "minItems": 1, "maxItems": MAX_SHOTS_CEILING, "items": _shot_schema(plan)},
    }
    return _object(fields, list(fields))


#: 布景用得到的物体种类 —— SceneObject.kind 里除了导入模型(没有文件)和灯之外的那些。
#: `group` 是**收纳**用的:八个布景台摊平就是七十多条重名的列表(「出租屋卧室」出现八次),
#: 谁也分不出哪个是哪个。每台一个组之后,列表是八行。
#: `model` 是**导入的模型**(通常在 Blender 里建好再收进工作区):基本体拼不出来的产品、道具、
#: 设备。它要配一个 model_id,而布景师是从上游「可用的 3D 道具」节点给的清单里拿到那个 id 的 ——
#: 没有那份清单时清单为空,布景师就只用基本体(提示词里说了)。
SET_KINDS = ["group", "room", "box", "cylinder", "sphere", "plane", "stairs", "table", "figure",
             "model", "camera"]


def _set_design_schema() -> dict[str, Any]:
    """布景的形状 = 3D 场景的数据格式(SceneContent),只收这条流程用得到的那部分。

    所有字段都列成必填(结构化输出的严格模式要求如此);用不上的给中性值 —— 非相机的 target/fov
    给 [0,1,0] / 45,不动的物体 track 给空数组。
    """
    vec3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    keyframe = {"time": {"type": "number", "minimum": 0}, "position": vec3, "target": vec3,
                "fov": {"type": "number", "minimum": 10, "maximum": 120}}
    parameters = {
        "width": {"type": "number", "minimum": 0.01}, "height": {"type": "number", "minimum": 0.01},
        "depth": {"type": "number", "minimum": 0.01}, "radius": {"type": "number", "minimum": 0.01},
        "steps": {"type": "integer", "minimum": 1, "maximum": 64},
    }
    obj = {
        "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": SET_KINDS},
        #: 归到哪个布景台的组下面;顶层物体(组自己)写空字符串。严格模式要求每一格都在,
        #: 所以用空串而不是 null 表示「没有父级」。
        "parent_id": {"type": "string"},
        "position": vec3, "rotation": vec3,
        #: 只有 kind="model" 用得上:上游道具清单里的那个 id。其余物体写空字符串
        #: (严格模式要求每一格都在)。
        "model_id": {"type": "string"},
        "parameters": _object(parameters, list(parameters)),
        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        "target": vec3, "fov": {"type": "number", "minimum": 10, "maximum": 120},
        "track": {"type": "array", "items": _object(keyframe, list(keyframe))},
    }
    shot = {
        "id": {"type": "string"}, "name": {"type": "string"},
        "duration": {"type": "number", "minimum": 0.1, "maximum": 120},
        "aspect": {"type": "string", "enum": ["16:9", "9:16", "1:1"]},
        "easing": {"type": "string", "enum": ["smooth", "linear"]},
        "camera_id": {"type": "string"},
    }
    lighting = {
        "preset": {"type": "string", "enum": ["custom"]},
        "azimuth": {"type": "number", "minimum": 0, "maximum": 359}, "elevation": {"type": "number", "minimum": 0, "maximum": 90},
        "intensity": {"type": "number", "minimum": 0, "maximum": 20},
        "temperature": {"type": "integer", "minimum": 1500, "maximum": 12000},
        "softness": {"type": "number", "minimum": 0, "maximum": 1},
    }
    fields = {
        "objects": {"type": "array", "maxItems": 480, "items": _object(obj, list(obj))},
        "shots": {"type": "array", "minItems": 1, "maxItems": 32, "items": _object(shot, list(shot))},
        "lighting": _object(lighting, list(lighting)),
        "background": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        "ambient": {"type": "number", "minimum": 0, "maximum": 10},
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
    return normalize_graph(graph, node_types=NODE_TYPES)


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
                # 所以先拆:人声那半丢掉、背景音留着,配音叠在背景音之上。装了分离引擎才做得到；
                # 没装时在排配音任务前明确失败，绝不能把用户选择静默改成整轨静音。
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
    return normalize_graph(graph, node_types=NODE_TYPES)


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
    *, chat: ModelChoice, image: ModelChoice, video: ModelChoice, voice_id: str = "", db: Session | None = None
) -> dict[str, Any]:
    """主题 → 主旨 → 脚本 / 视觉圣经 → 角色三视图 + 场景设定图 → 分镜 → 3D 白模布景 → 逐镜:
    白模参考 → 首帧(需要时加尾帧)→ 视频 → 按序上时间线 → 口播字幕 → 导出。

    此前每一镜只有一段文字提示词:构图、机位、人物长相全靠视频模型猜,几镜之间谁也对不上谁。
    现在一致性和镜头语言各有实物依据:

    - **人物**:每个角色先画一张三视图,之后所有关键帧和参考都带着它;
    - **场景**:每个场景先画一张设定图;
    - **构图与机位**:LLM 按分镜搭 3D 白模,每镜一个布景台、一台相机(推拉摇移都在相机轨迹上),
      后端渲出白模首尾帧和运镜视频,镜头语言从机位轨迹**算出来**进提示词;
    - **每镜两条路之一**(Seedance 这类模型上两组素材互斥,见 generation/catalog.SOURCE_GROUPS):
      `keyframes` 先按白模机位画首帧(需要时加尾帧)再出片,构图最稳;`references` 把三视图、
      设定图、白模帧和运镜视频直接交给视频模型,适合复杂运镜。走哪条由分镜逐镜决定,能选哪几条
      由视频模型的能力决定(见 VideoPlan.modes)。

    ``db`` 让模型的默认参数能读到用户自定义的参数声明;官网导出等无库上下文留空,退回内置目录。
    """
    video_plan = _video_plan(db, video)
    image_plan = _image_plan(db, image)
    clip = video_plan.clip_seconds
    aspect = video_plan.aspect_ratio if video_plan.aspect_ratio in ("16:9", "9:16", "1:1") else "16:9"
    frame_size = image_plan.frame_sizes.get(aspect, "")
    image_parameters = {"size": "{{input.frame_size}}"} if frame_size else {}
    sheet_parameters = {"size": image_plan.sheet_size} if image_plan.sheet_size else {}
    modes_text = " / ".join(video_plan.modes)

    brief_system = """你是资深创意总监和纪录片策划。先把用户给出的主题收敛为全片唯一核心主旨，
建立清晰的受众收益、叙事因果和可执行视觉母题。不要编造未经输入支持的具体数字、引语、人物经历
或研究结论；需要核实的内容写入 factual_boundaries。只输出符合 JSON Schema 的对象。"""

    narrative_system = """你是资深编剧和旁白导演。围绕唯一核心主旨规划完整叙事，不引入创意简报之外
的事实。按目标时长拆成首尾连续的叙事节拍：开头尽快建立观看理由，中段用因果而不是信息堆砌推进，
结尾回收主旨。口播要自然、可说、符合指定语言。只输出符合 JSON Schema 的对象。"""

    visual_system = """你是摄影指导、美术指导、角色设计和连续性监制。根据创意简报建立全片共享的视觉圣经：
主体、环境、光线、色彩、镜头语言与连续性规则，规则要具体到生成模型可以复用，避免空泛风格词。
同时定下**出镜角色**(最多 4 个；appearance 用英文写到能画出三视图的程度：年龄、脸型发型、服装与配色、
体型、标志性道具)和**场景**(最多 3 个；description 用英文写空间、陈设、材质与光源，给出大致的
长宽高)。每个角色分一个不同的白模颜色，并在 blockout_legend 里用英文说明颜色与角色的对应。
style_prompt 是一句英文画风，全片每张图、每段视频都会带上。不得要求画面生成字幕、UI、Logo 或水印。
只输出符合 JSON Schema 的对象。"""

    storyboard_system = f"""你是导演、摄影指导、分镜师和生成提示词工程师。把创意简报拆成连续的
{clip} 秒镜头。每镜给出精确起止时间、口播、场景(location_id)、出镜角色、人物站位与走位、景别、
机位角度、焦段(lens_mm)、运镜方式与路径、主体动作、光线、声音设计和连续性。所有镜头时间必须
首尾相接，不重叠、不留空；首镜建立钩子，中段逐步升级信息，末镜完成主旨回收。每镜 narration 念出来
不得超过 {clip} 秒：中文按每秒约 4 字、英文按每秒约 2.5 个词估算，宁短勿长；超出的部分会被加速压进
这一镜，听起来会很赶。

每镜选一条出片路径(reference_mode,可选:{modes_text}):keyframes 先按白模机位画首帧再生成,
构图最稳,适合绝大多数镜头;references 把角色三视图、场景设定图和白模运镜视频直接交给视频模型,
适合环绕、长距离跟拍这类首尾两帧说不清的复杂运镜。first_frame_prompt 用英文完整描述第一帧画面。
generation_prompt 用英文写动作节拍、表演、环境变化与光影，主体动作必须能在 {clip} 秒内完成；
**不要写机位参数**(机位会从白模自动算出来补上),画面中不要生成字幕、UI、Logo 或水印。
transition_in/out 是交付给后期查看的剪辑意图；本工作流自动合成阶段按时间顺序硬切。只输出符合
JSON Schema 的对象。"""

    set_system = f"""你是布景师兼摄影助理。按分镜给每个镜头搭一个 3D 白模布景台，并放好这一镜的相机。
输出就是 3D 场景的数据格式，会被直接建成场景、渲出参考帧交给图像和视频模型 —— 它决定每一镜的构图。

坐标约定：单位米，Y 朝上，地面 y=0；所有坐标都写**世界坐标**。

**台距 D 由布景尺寸算出来,不是固定值。** 取视觉圣经里最大的那个场景的 width_m 与 depth_m 中较大的
那个,加 8 米;若不足 12 米就按 12 米。第 n 镜(shot_number = n)的布景台整体放在 x = n*D 附近,
台内每一个物体和这一镜相机的 position / target 都要把 x 加上 n*D。
**不要用固定的 40 米**:三四米宽的卧室按 40 米排开,台与台之间会空出三十多米,整个白模散成一串
看不清的小点;而六十米的大场景在 40 米台距下会直接和隔壁穿模。

**每个布景台先出一个组。** kind="group",id="bay-<n>",name="镜头 <n> · <这一镜的场景名>",
position 写 [0,0,0],parent_id 写空字符串;这一台里的**每一个**物体(room、陈设、figure、相机)
都把 parent_id 写成 "bay-<n>"。组只为收纳,它在原点,所以**不改变任何坐标** —— 上面那条"都写世界
坐标"照旧成立。没有组的话,八个台摊平就是七十多条重名的平铺列表。

每个布景台：
- 一个 room(parameters.width/depth/height 取视觉圣经里这个场景的尺寸，position 为 [n*40,0,0]，
  门洞在前后墙正中；没有天花板)。室外场景用一块 plane 当地面、几块 box 当远景体块。
- 关键陈设用 box / cylinder / table / stairs 概括(桌椅、柜子、门、树……)，尺寸按真实比例。
- 这一镜出镜的每个角色一个 figure:parameters.height = 角色身高,width 0.4~0.5(肩宽),depth 0.22~0.28;
  color 用视觉圣经里这个角色的 blockout_color;position 按分镜的站位;rotation[1] 是朝向(度)。
  id 写成 "<角色id>-<n>"。
- **能用真道具就别用方块拼。** 下面那份「可用的 3D 道具」清单里的东西是已经建好的真实模型:
  kind="model",model_id 写清单里那个 id,name 写道具名,position/rotation 照常摆。清单里给了
  每件道具实测的长宽高,按它和 figure(人)的比例摆,不要再用 parameters 去"设定"它的尺寸
  (模型自带尺寸,parameters 对它无效)。清单为空就全用基本体。
- 物体的 target 写 [0,1,0]、fov 写 45、track 写空数组 —— 只有相机用得上它们;
  非 model 的物体 model_id 写空字符串。

每镜一台相机：kind="camera",id="cam-<n>";position 是起始机位,target 是起始看向点(一般是主体的胸口
或眼睛高度 1.3~1.6 米),fov 是竖直视角,由焦段换算:fov = 2*atan(12/焦段毫米)(14mm≈81°,24mm≈53°,
35mm≈38°,50mm≈27°,85mm≈16°,135mm≈10°)。机位高度按机位角度:平视 1.5~1.7 米,俯拍 2.5~4 米,
仰拍 0.3~0.8 米。相机必须在房间内、不穿过任何物体,和主体的距离要让景别成立(特写约 0.6~1 米,
中景 1.5~2.5 米,全景 3~5 米)。
运镜写在相机的 track 上：static 不写 track;其余至少两档 {{time:0,...}} 和 {{time:{clip},...}}
(position/target/fov 三项都写),推 = 沿视线靠近主体,拉 = 远离,摇 = 机位不动只转 target,
跟 = 机位和 target 一起平移,环绕 = 绕主体转(可加中间一档),升降 = 机位上下移动。

shots:每镜一条 {{id:"shot-<n>", name:"镜头 <n>", duration:{clip}, aspect:画幅, easing:"smooth",
camera_id:"cam-<n>"}}。lighting 按视觉圣经的光线方案给方位角(0=相机默认一侧,90=右侧,180=逆光)、
高度角、强度(2~5)、色温和软硬;preset 写 "custom"。background 写 "#20242c",ambient 写 1.5。
只输出符合 JSON Schema 的对象。"""

    frame_prompt_tail = (
        " Reference images: the first one is a grey 3D blockout of this exact shot — match its camera angle, lens, "
        "framing, horizon line and the placement of the coloured mannequins exactly ({{input.legend}}); the "
        "mannequins are stand-ins, render them as the real characters. The character turnaround sheets fix each "
        "character's face, hair, outfit and proportions; the location concept art fixes the set. Only the characters "
        "described above appear. {{input.style}}"
    )

    generate_body = {
        "nodes": [
            {
                "id": "render_blockout",
                "type": "scene_render",
                "name": {"zh": "渲染本镜白模参考", "en": "Render this shot's blockout"},
                "position": {"x": 80, "y": 140},
                "config": {
                    "scene_id": "{{input.scene_id}}",
                    "shot_id": "shot-{{loop.item.shot_number}}",
                    #: 静帧给首尾帧那条路,运镜视频给参考那条路。两样都渲:运镜视频也是给人检查机位的。
                    "render": "both",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "is_keyframes",
                "type": "condition",
                "name": {"zh": "这一镜走首尾帧吗", "en": "Does this shot use keyframes?"},
                "position": {"x": 390, "y": 60},
                "config": {"left": "{{loop.item.reference_mode}}", "op": "equals", "right": "keyframes"},
            },
            {
                "id": "paint_first_frame",
                "type": "ai_generate",
                "name": {"zh": "按白模机位画首帧", "en": "Paint the first frame on the blockout"},
                "position": {"x": 700, "y": 60},
                "config": {
                    "provider": image.provider,
                    "provider_profile_id": image.profile_id,
                    "model": image.model,
                    "kind": "image",
                    "prompt": "{{loop.item.first_frame_prompt}}" + frame_prompt_tail,
                    "parameters": image_parameters,
                    "source_assets": [
                        "{{render_blockout.first_frame_asset_id}}:reference_image",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                    ],
                },
            },
            {
                "id": "needs_last_frame",
                "type": "condition",
                "name": {"zh": "这一镜要尾帧吗", "en": "Does this shot need a last frame?"},
                "position": {"x": 1010, "y": 60},
                "config": {"left": "{{loop.item.last_frame_prompt}}", "op": "not_empty"},
            },
            {
                "id": "paint_last_frame",
                "type": "ai_generate",
                "name": {"zh": "按白模机位画尾帧", "en": "Paint the last frame on the blockout"},
                "position": {"x": 1320, "y": 60},
                "config": {
                    "provider": image.provider,
                    "provider_profile_id": image.profile_id,
                    "model": image.model,
                    "kind": "image",
                    "prompt": "{{loop.item.last_frame_prompt}} This is the last frame of the same shot whose first frame "
                              "is the second reference image — keep characters, wardrobe, lighting and set continuous."
                              + frame_prompt_tail,
                    "parameters": image_parameters,
                    "source_assets": [
                        "{{render_blockout.last_frame_asset_id}}:reference_image",
                        "{{paint_first_frame.asset_id}}:reference_image",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                    ],
                },
            },
            {
                "id": "generate_clip",
                "type": "ai_generate",
                "name": {"zh": f"生成 {clip} 秒镜头", "en": f"Generate the {clip}s shot"},
                "position": {"x": 1320, "y": 260},
                "config": {
                    "provider": video.provider,
                    "provider_profile_id": video.profile_id,
                    "model": video.model,
                    "kind": "video",
                    "prompt": "{{loop.item.generation_prompt}} Camera: {{render_blockout.camera_move}}. "
                              "Keep every character exactly as in the references. {{input.style}}",
                    "negative_prompt": "{{loop.item.negative_prompt}}",
                    "parameters": video_plan.parameters or {},
                    #: 两组都接上,由 source_group 逐镜选一组(Seedance 上两组互斥)。没跑的首尾帧是空行,
                    #: 自然消失;`{{input.sheets}}` 这样的整组引用在运行时摊平。
                    "source_assets": [
                        "{{paint_first_frame.asset_id}}:first_frame",
                        "{{paint_last_frame.asset_id}}:last_frame",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                        "{{render_blockout.first_frame_asset_id}}:reference_image",
                        "{{render_blockout.video_asset_id}}:reference_video",
                    ],
                    "source_group": "{{loop.item.reference_mode}}",
                },
            },
            {
                "id": "organize_clip",
                "type": "asset_update",
                "name": {"zh": "归档并命名镜头素材", "en": "File and name the shot's asset"},
                "position": {"x": 1630, "y": 260},
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
                "position": {"x": 80, "y": 420},
                "config": {"left": "{{input.voice_id}}", "op": "not_empty"},
            },
            {
                "id": "has_narration",
                "type": "condition",
                "name": {"zh": "这一镜有口播吗", "en": "Does this shot have narration?"},
                "position": {"x": 390, "y": 420},
                "config": {"left": "{{loop.item.narration}}", "op": "not_empty"},
            },
            {
                "id": "narrate",
                "type": "synthesize_speech",
                "name": {"zh": "合成该镜口播", "en": "Synthesise this shot's narration"},
                "position": {"x": 700, "y": 420},
                # 开始节点里填的是配音库音色的 id,所以引擎是克隆;想用引擎音色,改这里的两格。
                "config": {"text": "{{loop.item.narration}}", "engine": "clone", "voice": "{{input.voice_id}}"},
            },
        ],
        "edges": [
            {"id": "shot_blockout_mode", "source": "render_blockout", "target": "is_keyframes"},
            {"id": "shot_mode_first", "source": "is_keyframes", "target": "paint_first_frame", "branch": "true"},
            {"id": "shot_first_needs_last", "source": "paint_first_frame", "target": "needs_last_frame"},
            {"id": "shot_needs_last", "source": "needs_last_frame", "target": "paint_last_frame", "branch": "true"},
            #: 生成视频只挂在白模之后:首尾帧那两个节点在参考那条路上会被跳过,而它们被引用 ——
            #: 引用即依赖,生成会等它们落定(跑完或被跳过)再开始。
            {"id": "shot_blockout_generate", "source": "render_blockout", "target": "generate_clip"},
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
                    "end": clip,
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
                    # **放在这一镜画面开始的那一秒**,不是接在上一段口播后面。用的是画面片段**实际**
                    # 落下的位置,不是分镜里写的 start_seconds。
                    "at": "{{append_clip.timeline_start}}",
                    # 不裁(硬裁会把话切掉半句),比镜头长就加速塞进去,最多 1.5 倍。
                    "max_duration": clip,
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
    sheet_body = {
        "nodes": [{
            "id": "sheet",
            "type": "ai_generate",
            "name": {"zh": "画这个角色的三视图", "en": "Draw this character's turnaround"},
            "position": {"x": 80, "y": 140},
            "config": {
                "provider": image.provider,
                "provider_profile_id": image.profile_id,
                "model": image.model,
                "kind": "image",
                "prompt": "Character turnaround reference sheet for {{loop.item.name}}: {{loop.item.appearance}}. "
                          "Three full-body views of the same character side by side — front, side profile, back — "
                          "identical outfit and proportions, relaxed A-pose, plain white background, soft even studio "
                          "light, no text, no labels, no borders. {{input.style}}",
                "parameters": sheet_parameters,
            },
        }],
        "edges": [],
    }
    location_body = {
        "nodes": [{
            "id": "art",
            "type": "ai_generate",
            "name": {"zh": "画这个场景的设定图", "en": "Paint this location's concept art"},
            "position": {"x": 80, "y": 140},
            "config": {
                "provider": image.provider,
                "provider_profile_id": image.profile_id,
                "model": image.model,
                "kind": "image",
                "prompt": "Establishing concept art of {{loop.item.name}}: {{loop.item.description}}. "
                          "Wide view of the empty set, no people, no text. {{input.style}}",
                "parameters": sheet_parameters,
            },
        }],
        "edges": [],
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
                    #: 这一次最多做几镜。**它是成本的闸门**:每一镜都是一次付费的视频生成,
                    #: 而镜头数此前完全由模型按时长算,跑之前看不到要花多少。
                    "max_shots": 8,
                    "audience": "对该主题感兴趣的大众观众",
                    "tone": "专业、清晰、克制且有电影感",
                    "language": "简体中文",
                    #: 画幅只能是 16:9 / 9:16 / 1:1(3D 白模的镜头只有这三种)。改画幅时把
                    #: frame_size(关键帧图的尺寸)也改成同比例的一档。
                    "aspect_ratio": aspect,
                    "frame_size": frame_size,
                    "resolution": video_plan.resolution,
                    "width": video_plan.width,
                    "height": video_plan.height,
                    "fps": 30,
                    # 配音音色。**留空 = 不配音**(成片只有画面),而不是跑到一半失败。
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
            "name": {"zh": "定角色、场景与视觉圣经", "en": "Define characters, locations and the visual bible"},
            "position": {"x": 680, "y": 520},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": visual_system,
                "prompt": """创意简报：
{{creative_brief.text}}

画幅：{{start.aspect_ratio}}；表达气质：{{start.tone}}。
请建立整条视频共享的视觉圣经、摄影语言和跨镜头连续性规则，并定下出镜角色与场景。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_visual_bible",
                "json_schema": _visual_bible_schema(),
                "json_schema_strict": "true",
                "temperature": 0.55,
                "max_tokens": 5000,
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
            "id": "character_sheets",
            "type": "loop_foreach",
            "name": {"zh": "画每个角色的三视图", "en": "Draw every character's turnaround"},
            "position": {"x": 1040, "y": 620},
            "config": {
                "items": "{{visual_bible.json.characters}}",
                "inputs": {"style": "{{visual_bible.json.style_prompt}}"},
                "body": sheet_body,
                #: 每项交出一行 `素材:reference_image` —— 下游把整组一次接进参考图。
                "output": "{{sheet.asset_id}}:reference_image",
                "concurrency": 3,
            },
        },
        {
            "id": "location_art",
            "type": "loop_foreach",
            "name": {"zh": "画每个场景的设定图", "en": "Paint every location's concept art"},
            "position": {"x": 1040, "y": 820},
            "config": {
                "items": "{{visual_bible.json.locations}}",
                "inputs": {"style": "{{visual_bible.json.style_prompt}}"},
                "body": location_body,
                "output": "{{art.asset_id}}:reference_image",
                "concurrency": 3,
            },
        },
        {
            "id": "storyboard",
            "type": "llm",
            "name": {"zh": "按时间拆解分镜与机位", "en": "Break the script into timed shots and camera set-ups"},
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

视觉圣经(含角色与场景 id)：
{{{{visual_bible.text}}}}

成片目标时长：{{{{start.target_duration_seconds}}}} 秒；画幅：{{{{start.aspect_ratio}}}}；
语言：{{{{start.language}}}}。每个镜头固定 {clip} 秒。镜头数 = 目标时长 ÷ {clip} 向上取整，
但**最多 {{{{start.max_shots}}}} 镜**；两者冲突时以上限为准，把成片做短一点，
**不要**为了凑满时长而缩短单镜时长——单镜时长是固定的 {clip} 秒。时间码从 0 开始连续编号。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_timed_storyboard",
                "json_schema": _storyboard_schema(video_plan),
                "json_schema_strict": "true",
                "temperature": 0.65,
                "max_tokens": 12000,
            },
        },
        {
            #: 留空 = 这个工作区里的全部模型。模板装出来时通常一份都没有,清单因此是空的,
            #: 布景师照旧只用基本体 —— 等用户在 Blender 里建好道具收进来,不改图就生效。
            "id": "props",
            "type": "scene_props",
            "name": {"zh": "可用的 3D 道具", "en": "Available 3D props"},
            "position": {"x": 1400, "y": 460},
            "config": {"model_ids": ""},
        },
        {
            "id": "set_design",
            "type": "llm",
            "name": {"zh": "设计 3D 白模布景与机位", "en": "Design the 3D blockout sets and cameras"},
            "position": {"x": 1400, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": set_system,
                "prompt": """视觉圣经(角色身高与白模颜色、场景尺寸)：
{{visual_bible.text}}

分镜(每镜的场景、出镜角色、站位、景别、机位角度、焦段、运镜与路径)：
{{storyboard.text}}

可用的 3D 道具(kind="model" 时 model_id 只能从这里选;尺寸是实测值)：
{{props.catalog}}

画幅：{{start.aspect_ratio}}。请给每个镜头搭一个布景台并放好相机。""",
                "response_format": "json_schema",
                "json_schema_name": "blockout_scene",
                "json_schema": _set_design_schema(),
                "json_schema_strict": "true",
                "temperature": 0.2,
                "max_tokens": 16000,
            },
        },
        {
            "id": "build_set",
            "type": "scene_create",
            "name": {"zh": "搭建 3D 白模场景", "en": "Build the 3D blockout scene"},
            "position": {"x": 1720, "y": 300},
            "config": {
                "name": "{{creative_brief.json.title}} · 白模",
                "layout": "{{set_design.json}}",
            },
        },
        {
            "id": "generate_shots",
            "type": "loop_foreach",
            "name": {"zh": "逐镜生成画面与口播", "en": "Generate every shot's picture and narration"},
            "position": {"x": 2040, "y": 300},
            "config": {
                "items": "{{storyboard.json.shots}}",
                "inputs": {
                    "project_id": "{{video_project.project_id}}",
                    "voice_id": "{{start.voice_id}}",
                    "scene_id": "{{build_set.scene_id}}",
                    "sheets": "{{character_sheets.results}}",
                    "locations": "{{location_art.results}}",
                    "style": "{{visual_bible.json.style_prompt}}",
                    "legend": "{{visual_bible.json.blockout_legend}}",
                    "frame_size": "{{start.frame_size}}",
                    "aspect_ratio": "{{start.aspect_ratio}}",
                    "resolution": "{{start.resolution}}",
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
            "position": {"x": 2360, "y": 300},
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
            "position": {"x": 2680, "y": 300},
            "config": {
                "sequence_id": "{{video_project.sequence_id}}",
                "segments": "{{assemble_timeline.results}}",
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
            "position": {"x": 3000, "y": 300},
            "config": {"sequence_id": "{{video_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "成片完成通知", "en": "Video finished notice"},
            "position": {"x": 3320, "y": 120},
            "config": {
                "title": "视频已生成：{{creative_brief.json.title}}",
                "body": "脚本、角色三视图、3D 白模、各镜视频和最终合成均已完成。最终素材 ID：{{export_final.asset_id}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付完整制作结果", "en": "Hand over the finished production"},
            "position": {"x": 3320, "y": 480},
            "config": {
                "values": {
                    "title": "{{creative_brief.json.title}}",
                    "core_thesis": "{{creative_brief.json.core_thesis}}",
                    "creative_brief": "{{creative_brief.json}}",
                    "narrative_script": "{{narrative_script.json}}",
                    "visual_bible": "{{visual_bible.json}}",
                    "storyboard": "{{storyboard.json}}",
                    "character_sheets": "{{character_sheets.results}}",
                    "location_art": "{{location_art.results}}",
                    "blockout_scene_id": "{{build_set.scene_id}}",
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
        {"id": "visual_sheets", "source": "visual_bible", "target": "character_sheets"},
        {"id": "visual_locations", "source": "visual_bible", "target": "location_art"},
        {"id": "narrative_storyboard", "source": "narrative_script", "target": "storyboard"},
        {"id": "visual_storyboard", "source": "visual_bible", "target": "storyboard"},
        {"id": "storyboard_set", "source": "storyboard", "target": "set_design"},
        {"id": "set_build", "source": "set_design", "target": "build_set"},
        {"id": "build_generate", "source": "build_set", "target": "generate_shots"},
        {"id": "sheets_generate", "source": "character_sheets", "target": "generate_shots"},
        {"id": "locations_generate", "source": "location_art", "target": "generate_shots"},
        {"id": "project_generate", "source": "video_project", "target": "generate_shots"},
        {"id": "generate_assemble", "source": "generate_shots", "target": "assemble_timeline"},
        {"id": "assemble_subtitles", "source": "assemble_timeline", "target": "narration_subtitles"},
        {"id": "subtitles_export", "source": "narration_subtitles", "target": "export_final"},
        {"id": "export_notice", "source": "export_final", "target": "done_notice"},
        {"id": "export_output", "source": "export_final", "target": "output"},
    ]
    graph = {
        "meta": {"template_id": FULL_VIDEO_GENERATION, "template_version": 8, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
