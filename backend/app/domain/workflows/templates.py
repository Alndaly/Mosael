"""内置工作流模板。

模板是可编辑的普通工作流图，不是另一套隐藏执行器。创建时把用户已经选择的默认模型固化到
节点上；没设置默认时保留空值，让画布就绪检查准确指出需要补哪一项，而不是替用户猜供应商。
"""

from __future__ import annotations

from typing import Any

from app.db.models import Voice
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.template_requirements import (
    CHAT_MODEL,
    CLONED_VOICE,
    CheckStatus,
    REFERENCE_IMAGE_MODEL,
    REFERENCE_VIDEO_MODEL,
    SEPARATION_ENGINE,
    LIPSYNC_VIDEO_MODEL,
    SPEECH_VIDEO_MODEL,
    TRANSCRIPTION_ENGINE,
    requirement,
)
from app.domain.workflows.templates_business import (
    BUSINESS_TEMPLATE_CATALOG,
    FABRIC_LOOKBOOK,
    FOOTAGE_MONTAGE,
    HIGHLIGHT_SHORTS,
    PRODUCT_ON_MODEL,
    PRODUCT_PITCH_PRESENTER,
    PRODUCT_PITCH_SHORT,
    TALKING_SCRIPT_VIDEO,
    fabric_lookbook_graph,
    footage_montage_graph,
    highlight_shorts_graph,
    product_on_model_graph,
    product_pitch_short_graph,
    talking_script_video_graph,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

#: 模型挑选、Schema 与三张大图住在旁边的 templates_* 模块里;这里重新导出每一个名字 ——
#: 调用方(路由、执行器、测试)照旧从 templates 取。
from app.domain.workflows.templates_models import (
    ModelChoice,  # noqa: F401
    VideoPlan,  # noqa: F401
    ImagePlan,  # noqa: F401
    _default_model,  # noqa: F401
    _capabilities,  # noqa: F401
    REFERENCE_IMAGES_NEEDED,  # noqa: F401
    _can_take_references,  # noqa: F401
    _can_shoot_from_references,  # noqa: F401
    _pick,  # noqa: F401
    _chat_model,
    _shot_video_model,
    _reference_image_model,
    _image_plan,  # noqa: F401
    _video_plan,  # noqa: F401
)
from app.domain.workflows.templates_schemas import (
    _object,  # noqa: F401
    _creative_brief_schema,  # noqa: F401
    _narrative_script_schema,  # noqa: F401
    BLOCKOUT_COLORS,  # noqa: F401
    _visual_bible_schema,  # noqa: F401
    SHOT_SIZES,  # noqa: F401
    CAMERA_ANGLES,  # noqa: F401
    CAMERA_MOVES,  # noqa: F401
    _shot_schema,  # noqa: F401
    MAX_SHOTS_CEILING,  # noqa: F401
    _storyboard_schema,  # noqa: F401
    SET_KINDS,  # noqa: F401
    _set_design_schema,  # noqa: F401
)
from app.domain.workflows.templates_cleanup import (
    TRANSCRIPT_VIDEO_CLEANUP,
    _cleanup_schema,  # noqa: F401
    transcript_video_cleanup_graph,
)
from app.domain.workflows.templates_dub import (
    TRANSLATED_DUB,
    TRANSLATED_DUB_LIPSYNC,
    translated_dub_graph,
)
from app.domain.workflows.templates_full_video import (
    FULL_VIDEO_GENERATION,
    _COORDINATES,  # noqa: F401
    _PROP_RULE,  # noqa: F401
    _camera_rules,  # noqa: F401
    blockout_rules,  # noqa: F401
    single_set_rules,  # noqa: F401
    full_video_generation_graph,
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
            "zh": "输入一个主题，生成创意主旨、脚本和视觉圣经；角色和场景先到资产库里认，已有的直接用它的参考图，新出现的才画三视图 / 设定图并存成资产，按分镜自动搭 3D 白模并摆好每一镜的机位与运镜；再逐镜按白模画首帧（需要时加尾帧）或直接用三视图与白模运镜视频做参考生成视频，按顺序组装、配上口播字幕并导出。花费量级：默认最多 8 镜，每镜一次视频生成外加 1~2 张关键帧，另有最多 7 张角色三视图与场景设定图（库里已有的不再画）、5 次对话和逐镜配音——是所有模板里最贵的一条，开始节点的 max_shots 就是镜头数的上限。",
            "en": "Turn a topic into a creative brief, script and visual bible; characters and locations already in the asset library are reused with their references, and only new ones get a turnaround sheet or concept art — saved to the library — auto-build a 3D blockout with each shot's camera position and move, then generate each shot from a first frame (and a last frame where needed) painted on the blockout — or straight from the turnarounds and the blockout camera move — and assemble, caption and export the video. Cost: by default up to 8 shots, each one video generation plus one or two keyframe images, on top of up to 7 turnaround and location images (none for those already in the library), 5 chat calls and per-shot narration — the most expensive template here; max_shots on the start node caps the shot count."
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(
                REFERENCE_IMAGE_MODEL,
                zh="能带参考图出图的图像模型（如 Seedream 4）",
                en="Image model that takes reference images (e.g. Seedream 4)",
            ),
            requirement(
                REFERENCE_VIDEO_MODEL,
                zh="支持首帧或参考素材的视频模型（如 Seedance 2.0）",
                en="Video model that takes a first frame or references (e.g. Seedance 2.0)",
            ),
            requirement(CLONED_VOICE, zh="旁白可选：克隆音色", en="Optional narration: cloned voice", optional=True),
        ],
        "stages": {
            "zh": [
                "输入主题",
                "脚本、角色与视觉圣经",
                "认已有资产，新的画三视图 / 设定图并存进资产库",
                "分镜与机位",
                "搭建 3D 白模",
                "逐镜：白模参考 → 首尾帧 → 视频",
                "按顺序组装并配字幕",
                "导出成片"
            ],
            "en": [
                "Choose a topic",
                "Script, characters and visual bible",
                "Reuse library assets; draw and save new turnarounds and location art",
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
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(None, zh="待整理的视频素材", en="Source video"),
        ],
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
        "requires": [
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(
                CHAT_MODEL,
                zh="翻译：AI 对话模型（节点上可换成 Google 翻译）",
                en="Translation: a chat model (switchable to Google Translate on the node)",
            ),
            #: 克隆音色和引擎自带音色都算数 —— 后一种要逐个引擎去问,这里不查,交给节点上的音色格。
            requirement(
                None,
                zh="一把嗓子：配音库的克隆音色，或某个引擎的现成音色",
                en="A voice: a cloned voice, or a built-in voice from any engine",
            ),
            requirement(SEPARATION_ENGINE, zh="人声分离引擎（需提前安装）", en="A voice separation engine installed in advance"),
            requirement(None, zh="有人说话的视频素材", en="A video with speech"),
        ],
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
    },
    {
        "id": TRANSLATED_DUB_LIPSYNC,
        "name": {"zh": "视频翻译 · 改口型", "en": "Translated dubbing with lip-sync"},
        "summary": {
            "zh": "在「视频译配」的基础上,配完音再让原片里说话人的嘴对上译文配音:按两句之间的空当把原片切成模型收得下的块,有配音的块改口型,接回整段盖在原片上(原片不动,删掉那条轨就回到原样),导出成片带「AI 生成」标识。运行前在「让原片的嘴对上配音」上确认已取得本人授权。",
            "en": "Everything in translated dubbing, then re-sync the speaker's lips to the translated dub: cut the source into chunks the model accepts at the gaps between lines, lip-sync the chunks with speech, and lay the joined result over the source (the source is untouched — delete that track to undo). The export carries an \"AI-generated\" label. Confirm the speaker's consent on the lip-sync step before running.",
        },
        "requires": [
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(CHAT_MODEL, zh="翻译:AI 对话模型", en="Translation: a chat model"),
            requirement(None, zh="一把嗓子:配音库的克隆音色,或某个引擎的现成音色", en="A voice: a cloned voice, or a built-in voice from any engine"),
            requirement(SEPARATION_ENGINE, zh="人声分离引擎(需提前安装)", en="A voice separation engine installed in advance"),
            requirement(LIPSYNC_VIDEO_MODEL, zh="会改口型的视频模型(比如百炼 videoretalk)", en="A lip-sync video model (for example Bailian videoretalk)"),
            requirement(None, zh="单人、正脸清楚的说话视频", en="A video of one person speaking, face clearly visible"),
        ],
        "stages": {
            "zh": ["选择视频", "生成带时间码逐字稿", "逐句翻译", "按原时间码铺译文字幕", "逐条配音并压回原长度", "让原片的嘴对上配音", "导出成片"],
            "en": ["Choose a video", "Transcribe with timecodes", "Translate line by line", "Lay subtitles on the original timecodes",
                   "Dub and time-compress", "Re-sync the lips to the dub", "Export"],
        },
    },
] + BUSINESS_TEMPLATE_CATALOG


def built_in_template_graph(
    db: Session, template_id: str, *, user_id: str, workspace_id: str = "", locale: str | None = None
) -> dict[str, Any]:
    """按模板造一张图。**节点名在这一刻定语言** —— 图一落库就是用户的数据(他随时可以改名),
    出口再翻就等于翻用户自己写的字。翻译贴着模板里的节点写(见 core.i18n.pick_text),
    和插件清单同一套。"""
    chat = _chat_model(db, user_id)
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
    if template_id in (TRANSLATED_DUB, TRANSLATED_DUB_LIPSYNC):
        # 音色和整片生成那条一样按工作区取:克隆音色存在工作区名下,不跟人走。
        return localised_names(locale, translated_dub_graph(
            chat=chat, voice_id=_first_voice_id(db, workspace_id), lipsync=template_id == TRANSLATED_DUB_LIPSYNC))
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
            # 出图尺寸和视频的时长 / 画幅按模型的参数声明挑(用户自定义的声明也算)。
            db=db,
        ))
    if template_id in (PRODUCT_PITCH_SHORT, PRODUCT_PITCH_PRESENTER):
        return localised_names(locale, product_pitch_short_graph(
            chat=chat,
            image=_reference_image_model(db, user_id),
            voice_id=_first_voice_id(db, workspace_id),
            presenter=template_id == PRODUCT_PITCH_PRESENTER,
            db=db,
        ))
    if template_id == TALKING_SCRIPT_VIDEO:
        # 音色按工作区取(克隆音色存在工作区名下);说话照片模型不在图里写死,节点按描述符挑会的那一个。
        return localised_names(locale, talking_script_video_graph(voice_id=_first_voice_id(db, workspace_id)))
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


def _engines_status(runtime_status, engines: list[str]) -> CheckStatus:
    """本地引擎(转写、人声分离)**有一个跑得起来就算齐**;探测还没回来的,说「还不知道」。

    探测要起子进程 import torch,十几秒 —— 这里只读已知的结果,没测过的交给后台去测。
    """
    known_all = True
    for engine in engines:
        ready, known = runtime_status(engine)
        if ready:
            return "met"
        known_all = known_all and known
    return "missing" if known_all else "unknown"


def requirement_statuses(db: Session, *, user_id: str, workspace_id: str) -> dict[str, CheckStatus]:
    """模板前置条件里**能自动查的那几样**,对这个人、这个工作区各是什么状态。

    判据和「用这个模板建一张图」时挑模型的是**同一套**(`_pick` / `_reference_image_model` /
    `_shot_video_model` / `_first_voice_id`):这里说齐了,建出来的图上那一格就是填好的;
    这里说缺,那一格就是空的。两处各写一份判据的话,迟早一处说齐、一处留空。
    """
    from app.ai.runtime import asr_models, separation_models
    from app.domain import audio_capabilities
    from app.domain.voices import transcription
    from app.domain.workflows.executors.talking import SPEECH_TO_VIDEO, VIDEO_LIPSYNC, talking_models

    has_chat = bool(_chat_model(db, user_id).model)
    statuses: dict[str, CheckStatus] = {
        CHAT_MODEL: "met" if has_chat else "missing",
        REFERENCE_IMAGE_MODEL: "met" if _reference_image_model(db, user_id).model else "missing",
        REFERENCE_VIDEO_MODEL: "met" if _shot_video_model(db, user_id).model else "missing",
        CLONED_VOICE: "met" if _first_voice_id(db, workspace_id) else "missing",
        TRANSCRIPTION_ENGINE: _plugin_or(db, user_id, transcription.CAPABILITY)
        or _engines_status(asr_models.runtime_status, list(transcription.LOCAL_ENGINES)),
        SEPARATION_ENGINE: _plugin_or(db, user_id, audio_capabilities.SEPARATION)
        or _engines_status(separation_models.runtime_status, list(separation_models.ENGINES)),
        SPEECH_VIDEO_MODEL: "met" if talking_models(db, SPEECH_TO_VIDEO, user_id) else "missing",
        LIPSYNC_VIDEO_MODEL: "met" if talking_models(db, VIDEO_LIPSYNC, user_id) else "missing",
    }
    return statuses


def _plugin_or(db: Session, user_id: str, capability: Any) -> CheckStatus | None:
    """这项能力有一家配好了的插件连接就算齐了(ADR 0032:插件和本机引擎并列);没有回 None,再去看本机引擎。"""
    from app.domain import capabilities

    ready = any(not one.missing for one in capabilities.plugin_providers(db, user_id, capability))
    return "met" if ready else None


