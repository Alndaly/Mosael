"""内置工作流模板。

模板是可编辑的普通工作流图，不是另一套隐藏执行器。创建时把用户已经选择的默认模型固化到
节点上；没设置默认时保留空值，让画布就绪检查准确指出需要补哪一项，而不是替用户猜供应商。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.core.i18n import tr
from app.db.models import Voice
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.template_requirements import (
    CHAT_MODEL,
    CLONED_VOICE,
    CheckStatus,
    DIGITAL_HUMAN_VOICE,
    MULTI_REFERENCE_IMAGE_MODEL,
    MULTI_REFERENCE_VIDEO_MODEL,
    REFERENCE_IMAGE_MODEL,
    REFERENCE_VIDEO_MODEL,
    SEPARATION_ENGINE,
    LIPSYNC_VIDEO_MODEL,
    SPEECH_VIDEO_MODEL,
    TIKHUB_ACCOUNT,
    TIKHUB_COMMENTS,
    TIKHUB_VIDEO,
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
from app.domain.workflows.templates_analysis import (
    ACCOUNT_ANALYSIS,
    ANALYSIS_TEMPLATE_CATALOG,
    COMMENT_INSIGHTS,
    VIRAL_VIDEO_BREAKDOWN,
    account_analysis_graph,
    comment_insights_graph,
    tikhub_problem,
    tikhub_status,
    viral_video_breakdown_graph,
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
    REFERENCE_IMAGES_NEEDED,
    SINGLE_REFERENCE,
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
#: 手里已有的东西** —— 一条长视频、一张商品图;最后是分析类(templates_analysis),产出的是一份分析笔记。
#: 拼在一起是因为模板库只有一份清单。
TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "full_video_generation",
        "name": {
            "zh": "从主题到完整视频",
            "en": "Topic to finished video"
        },
        "summary": {
            "zh": "输入一个主题，生成创意主旨、脚本和视觉圣经；角色和场景先到资产库里认，已有的直接用它的参考图，新出现的才画三视图 / 设定图并存成资产，按分镜自动搭 3D 白模并摆好每一镜的机位与运镜；再逐镜按白模画首帧（需要时加尾帧）或直接用三视图与白模运镜视频做参考生成视频，按顺序组装、配上口播字幕并导出。花费量级：默认最多 8 镜，每镜一次视频生成外加 1~2 张关键帧，另有最多 7 张角色三视图与场景设定图（库里已有的不再画）、5 次对话和逐镜配音——是所有模板里最贵的一条，开始节点的 max_shots 就是镜头数的上限，shot_seconds 是每镜几秒（建图时按所选视频模型取它能出的、最接近默认的那一档）。",
            "en": "Turn a topic into a creative brief, script and visual bible; characters and locations already in the asset library are reused with their references, and only new ones get a turnaround sheet or concept art — saved to the library — auto-build a 3D blockout with each shot's camera position and move, then generate each shot from a first frame (and a last frame where needed) painted on the blockout — or straight from the turnarounds and the blockout camera move — and assemble, caption and export the video. Cost: by default up to 8 shots, each one video generation plus one or two keyframe images, on top of up to 7 turnaround and location images (none for those already in the library), 5 chat calls and per-shot narration — the most expensive template here; max_shots on the start node caps the shot count, and shot_seconds sets each shot's length (preset to the length the chosen video model can make that is closest to its default)."
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(
                MULTI_REFERENCE_IMAGE_MODEL,
                zh="能同时带多张参考图出图的图像模型（如 Seedream 4）",
                en="Image model that takes several reference images at once (e.g. Seedream 4)",
            ),
            requirement(
                MULTI_REFERENCE_VIDEO_MODEL,
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
            "zh": "先去除底噪，再将视频转为带时间码的逐字稿，识别停顿、口头禅与重复内容，生成裁切方案和整理版视频。保留原素材。适合 30 分钟以内的口播、访谈；更长的素材先分段再整理。",
            "en": "Remove background hiss, transcribe the video with timestamps, identify pauses, fillers and repetition, then create a cut plan and a cleaned video while preserving the original. Suited to talks and interviews up to about 30 minutes; split longer footage first."
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
            "zh": "把一段视频逐句转写、逐句翻译，按原时间码铺上译文字幕，再逐条配音并变速压回原段落长度。目标语言在「逐句翻译」一步上选（默认英文）。原声里的人声拆出去、背景音乐留着；开始前需装好人声分离引擎。",
            "en": "Transcribe a video sentence by sentence, translate each line, lay translated subtitles on the original timecodes, then dub each line and time-compress it back into its own slot. Pick the target language on the translate step (English by default). The original voice is separated out and the background music kept; a voice separation engine must be ready before the workflow starts."
        },
        "requires": [
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(
                CHAT_MODEL,
                zh="翻译：AI 对话模型（节点上可换成 Google 翻译）",
                en="Translation: a chat model (switchable to Google Translate on the node)",
            ),
            #: 配音节点的引擎写的是本机克隆(builtin:clone),所以查的是「有克隆音色、克隆引擎跑得起来」。
            #: 换成别的引擎的现成音色也行 —— 那要逐个引擎去问,这里不查,句子里说清楚。
            requirement(
                CLONED_VOICE,
                zh="一把嗓子：配音库的克隆音色（节点上也可换成某个引擎的现成音色）",
                en="A voice: a cloned voice (switchable on the node to a built-in voice from any engine)",
            ),
            requirement(SEPARATION_ENGINE, zh="人声分离引擎（需提前安装）", en="A voice separation engine installed in advance"),
            requirement(None, zh="有人说话的视频素材", en="A video with speech"),
        ],
        "stages": {
            "zh": [
                "选择视频",
                "选择目标语言",
                "生成带时间码逐字稿",
                "逐句翻译",
                "按原时间码铺译文字幕",
                "逐条配音并压回原长度",
                "导出译配成片"
            ],
            "en": [
                "Choose a video",
                "Choose the target language",
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
        "name": {"zh": "视频译配 · 改口型", "en": "Translated dubbing with lip-sync"},
        "summary": {
            "zh": "在「视频译配 · 字幕与配音」的基础上,配完音再让原片里说话人的嘴对上译文配音:按两句之间的空当把原片切成模型收得下的块,有配音的块改口型,接回整段放在最上面一条视频轨、盖住原片(删掉那条轨就回到改口型之前),导出成片带「AI 生成」标识。目标语言在「逐句翻译」一步上选(默认英文)。运行前在「让原片的嘴对上配音」上确认已取得本人授权。费用量级:改口型按原片时长计费(百炼 videoretalk 挂牌价约 0.08 元/秒,一分钟的片子约 5 元),另加翻译和逐句配音;重跑时,译文、音色和时间都没变的块不再重买(改了哪句译文,那一块重买)。",
            "en": "Everything in translated dubbing with subtitles, then re-sync the speaker's lips to the translated dub: cut the source into chunks the model accepts at the gaps between lines, lip-sync the chunks with speech, and lay the joined result on the top video track over the source (delete that track to undo the lip-sync). The export carries an \"AI-generated\" label. Pick the target language on the translate step (English by default). Confirm the speaker's consent on the lip-sync step before running. Cost: lip-sync is billed by source length (Bailian videoretalk lists about 0.08 CNY per second, so roughly 5 CNY a minute), plus translation and per-line dubbing; a re-run doesn't pay again for chunks whose translation, voice and timing are unchanged (a reworded line re-buys its chunk).",
        },
        "requires": [
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(CHAT_MODEL, zh="翻译:AI 对话模型(节点上可换成 Google 翻译)",
                        en="Translation: a chat model (switchable to Google Translate on the node)"),
            #: 配音要交给改口型:克隆音色得声明过是谁的(ADR 0028 §5)。
            requirement(DIGITAL_HUMAN_VOICE, zh="一把嗓子:声明过是谁的克隆音色(节点上也可换成某个引擎的现成音色)",
                        en="A voice: a cloned voice with a consent declaration (switchable on the node to a built-in voice)"),
            requirement(SEPARATION_ENGINE, zh="人声分离引擎(需提前安装)", en="A voice separation engine installed in advance"),
            requirement(LIPSYNC_VIDEO_MODEL, zh="会改口型的视频模型(比如百炼 videoretalk)", en="A lip-sync video model (for example Bailian videoretalk)"),
            requirement(None, zh="单人、正脸清楚的说话视频", en="A video of one person speaking, face clearly visible"),
        ],
        "stages": {
            "zh": ["选择视频", "选择目标语言", "生成带时间码逐字稿", "逐句翻译", "按原时间码铺译文字幕", "逐条配音并压回原长度",
                   "让原片的嘴对上配音", "导出成片"],
            "en": ["Choose a video", "Choose the target language", "Transcribe with timecodes", "Translate line by line",
                   "Lay subtitles on the original timecodes", "Dub and time-compress", "Re-sync the lips to the dub", "Export"],
        },
    },
] + BUSINESS_TEMPLATE_CATALOG + ANALYSIS_TEMPLATE_CATALOG


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
            image=_reference_image_model(db, user_id, needed=REFERENCE_IMAGES_NEEDED),
            video=_shot_video_model(db, user_id),
            # 音色是工作区的(克隆音色存在工作区名下),所以按工作区取,不按人。
            voice_id=_prefilled_voice_id(db, workspace_id),
            db=db,
        ))
    if template_id == TRANSCRIPT_VIDEO_CLEANUP:
        return localised_names(locale, transcript_video_cleanup_graph(chat=chat, locale=locale))
    if template_id in (TRANSLATED_DUB, TRANSLATED_DUB_LIPSYNC):
        # 音色和整片生成那条一样按工作区取:克隆音色存在工作区名下,不跟人走。
        # 改口型那一版的配音要交给数字人:只预填声明过是谁的克隆音色。
        lipsync = template_id == TRANSLATED_DUB_LIPSYNC
        return localised_names(locale, translated_dub_graph(
            chat=chat, voice_id=_prefilled_voice_id(db, workspace_id, digital_human=lipsync), lipsync=lipsync, locale=locale))
    if template_id == HIGHLIGHT_SHORTS:
        # 不生成画面,所以只要对话模型;转写引擎由节点自己挑。
        return localised_names(locale, highlight_shorts_graph(chat=chat))
    if template_id == PRODUCT_ON_MODEL:
        return localised_names(locale, product_on_model_graph(
            chat=chat,
            # 商品图要当参考图贯穿每一次出图,所以挑的是"能带参考图出图"的那个,不是随便一个图像模型。
            # 每次只带那一张商品图:门槛是 1 张,不是整片生成的 9 张。
            image=_reference_image_model(db, user_id, needed=SINGLE_REFERENCE),
            # 视频是**可选**的一步:没有合适的视频模型就只出静图,而不是让整条模板用不了。
            # 动起来那一步只交那一张上身图:参考那条路的门槛是 1 张,不是整片一镜的一整组。
            video=_shot_video_model(db, user_id, references=SINGLE_REFERENCE),
            # 出图尺寸和视频的时长 / 画幅按模型的参数声明挑(用户自定义的声明也算)。
            db=db,
        ))
    if template_id in (PRODUCT_PITCH_SHORT, PRODUCT_PITCH_PRESENTER):
        return localised_names(locale, product_pitch_short_graph(
            chat=chat,
            image=_reference_image_model(db, user_id, needed=SINGLE_REFERENCE),
            # 「每一拍动起来」是**可选**的一步,和上身图「把这一组动起来」同一个挑法:有能从这一拍的画面出片的视频模型
            # 就每拍出一段视频,没有就和此前一样每拍一张静图。只交这一拍的画面一张,门槛是 1 张。
            video=_shot_video_model(db, user_id, references=SINGLE_REFERENCE),
            voice_id=_prefilled_voice_id(db, workspace_id),
            presenter=template_id == PRODUCT_PITCH_PRESENTER,
            db=db,
            locale=locale,
        ))
    if template_id == TALKING_SCRIPT_VIDEO:
        # 音色按工作区取(克隆音色存在工作区名下);说话照片模型不在图里写死,节点按描述符挑会的那一个。
        return localised_names(locale, talking_script_video_graph(
            voice_id=_prefilled_voice_id(db, workspace_id, digital_human=True)))
    if template_id == FOOTAGE_MONTAGE:
        # 不生成画面,所以只要对话模型;音色按工作区取,没有就只出字幕(图里由条件挡掉旁白那两步)。
        return localised_names(locale, footage_montage_graph(chat=chat, voice_id=_prefilled_voice_id(db, workspace_id)))
    if template_id == FABRIC_LOOKBOOK:
        return localised_names(locale, fabric_lookbook_graph(
            chat=chat,
            image=_reference_image_model(db, user_id, needed=SINGLE_REFERENCE),
        ))
    #: 分析类:只要对话模型;取数走 TikHub 插件或内嵌浏览器,由开始节点的 data_source 选(见 templates_analysis)。
    if template_id == ACCOUNT_ANALYSIS:
        return localised_names(locale, account_analysis_graph(chat=chat, locale=locale))
    if template_id == VIRAL_VIDEO_BREAKDOWN:
        return localised_names(locale, viral_video_breakdown_graph(chat=chat, locale=locale))
    if template_id == COMMENT_INSIGHTS:
        return localised_names(locale, comment_insights_graph(chat=chat, locale=locale))
    raise WorkflowDomainError("wfErr_unknownTemplate", params={"id": template_id})


def blank_template_graphs(locale: str) -> dict[str, dict[str, Any]]:
    """每个官方模板**不带任何本机选择**的那一份:模型、音色留空,由用的人挑。官网下载的就是它
    (scripts/sync-website-workflows.py);现行模板的版本号也从它读(current_template_versions)。

    **按这一份的语言建** —— 图里给人看的默认值(新项目的名字、完成通知)在建图时定语言,和节点名同一条
    (见 transcript_video_cleanup_graph / translated_dub_graph)。
    """
    blank = ModelChoice()
    return {
        #: 视频模型留空 = 按"还没挑模型"出片计划:每镜秒数默认 5、只走首帧那条路。**首帧是每一个能用的视频模型都收的
        #: 那一条**(参考素材那条只有部分模型收),而导入的人挑哪个模型这里不知道。出图 / 视频的画幅、尺寸、分辨率
        #: 照样接到开始参数(templates_models._video_plan):挑模型时编辑器只留新模型仍收的绑定和值(前端
        #: carriedParameters),不收 5 秒的模型由运行前检查在花钱之前说清。
        FULL_VIDEO_GENERATION: full_video_generation_graph(chat=blank, image=blank, video=blank),
        TRANSCRIPT_VIDEO_CLEANUP: transcript_video_cleanup_graph(chat=blank, locale=locale),
        # 音色按工作区取,不带任何本机资源的那份留空,由用的人自己挑。
        TRANSLATED_DUB: translated_dub_graph(chat=blank, voice_id="", locale=locale),
        TRANSLATED_DUB_LIPSYNC: translated_dub_graph(chat=blank, voice_id="", lipsync=True, locale=locale),
        HIGHLIGHT_SHORTS: highlight_shorts_graph(chat=blank),
        #: 上身图这条按**带视频**导出(`motion=True`),视频模型那一格留空,由导入的人挑;没有视频模型的话,在画布上
        #: 删掉「把这一组动起来」和「归档这一组的视频」两个节点即可(卡片的 download_note 说给下载的人听)——
        #: 循环交出的是上身图,不依赖它们。反过来(导成不带视频)则是有视频模型的人看不到那一步,而他不会知道本来有。
        PRODUCT_ON_MODEL: product_on_model_graph(chat=blank, image=blank, video=blank, motion=True),
        #: 带货口播同上身图:按**每一拍动起来**导出(`motion=True`),视频模型那一格留空,由导入的人挑;没有视频模型的话,
        #: 照卡片的 download_note 在画布上去掉那一步 —— 反过来导成静图版,有视频模型的人看不到这一步。
        PRODUCT_PITCH_SHORT: product_pitch_short_graph(chat=blank, image=blank, video=blank, motion=True, voice_id="",
                                                       locale=locale),
        PRODUCT_PITCH_PRESENTER: product_pitch_short_graph(chat=blank, image=blank, video=blank, motion=True, voice_id="",
                                                           presenter=True, locale=locale),
        FABRIC_LOOKBOOK: fabric_lookbook_graph(chat=blank, image=blank),
        FOOTAGE_MONTAGE: footage_montage_graph(chat=blank, voice_id=""),
        TALKING_SCRIPT_VIDEO: talking_script_video_graph(voice_id=""),
        #: 分析类只有对话模型那一格(留空);TikHub 的连接、浏览器的登录档案都是用的人在本机选的。
        ACCOUNT_ANALYSIS: account_analysis_graph(chat=blank, locale=locale),
        VIRAL_VIDEO_BREAKDOWN: viral_video_breakdown_graph(chat=blank, locale=locale),
        COMMENT_INSIGHTS: comment_insights_graph(chat=blank, locale=locale),
    }


@lru_cache(maxsize=1)
def current_template_versions() -> dict[str, int]:
    """每个官方模板现在是第几版(图上的 meta.template_version)。模板改了会让旧图失败的地方就加一版:
    从旧版建出来的图在编辑器顶上提示「按新版重建」(见 rebuilt_from_template)。"""
    return {template_id: int(graph["meta"]["template_version"]) for template_id, graph in blank_template_graphs("zh").items()}


def rebuilt_from_template(
    db: Session, graph: dict[str, Any], *, user_id: str, workspace_id: str, locale: str | None
) -> dict[str, Any]:
    """按**现行**模板给这张从官方模板建出来的图重建一张,带上用户填过的东西。

    1.8.0 时从模板建的图没有迁移:上身图动起来必败、混剪没有旁白的那段必败、带货只念钩子……而图一落库就是用户的
    数据(他可能改过),不能替他悄悄改写。所以不迁移,而是在编辑器顶上提示,由他点一下按新版重建一张(旧图保留)。

    带过去的:开始参数里新版还有的那几格(填过的值),以及节点 id 和类型都没变的节点上、新版留空而旧图填过的
    字面量(挑的素材、主播、贴的稿子、授权确认……,循环体里的也算)。模型按现在的设置重新挑,新版填了的格子不覆盖。
    """
    meta = graph.get("meta") if isinstance(graph.get("meta"), dict) else {}
    template_id = str(meta.get("template_id") or "")
    if meta.get("source") != "official" or template_id not in current_template_versions():
        raise WorkflowDomainError("wfErr_notFromTemplate")
    fresh = built_in_template_graph(db, template_id, user_id=user_id, workspace_id=workspace_id, locale=locale)
    _carry_picks(fresh, graph)
    return fresh


def _carry_picks(fresh: dict[str, Any], old: dict[str, Any]) -> None:
    previous = {str(node.get("id")): node for node in old.get("nodes") or [] if isinstance(node, dict)}
    for node in fresh.get("nodes") or []:
        before = previous.get(str(node.get("id")))
        if before is None or before.get("type") != node.get("type"):
            continue
        config, old_config = node.get("config") or {}, before.get("config") or {}
        if node.get("type") == "start":
            params, old_params = config.get("params") or {}, old_config.get("params") or {}
            #: 新版里只能从几项里选的参数,只带选项里有的值 —— 旧版那一格可能是手填的(「TikHub」「浏览器」),
            #: 带过去只会在运行前被拦;不带就留空,面板上那一行说「必填,还没选」,由人挑。
            options = config.get("param_options") if isinstance(config.get("param_options"), dict) else {}
            for key in params:
                kept = old_params.get(key)
                if kept in (None, ""):
                    continue
                if key in options and kept not in {one.get("value") for one in options[key] if isinstance(one, dict)}:
                    continue
                params[key] = copy.deepcopy(kept)
            continue
        bound = set(node.get("inputs") or [])
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(old_config.get(key), dict) and isinstance(value.get("nodes"), list):
                _carry_picks(value, old_config[key])
                continue
            kept = old_config.get(key)
            if value in (None, "") and key not in bound and isinstance(kept, (str, int, float)) and kept != "" \
                    and "{{" not in str(kept):
                config[key] = kept


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


def _first_voice_id(db: Session, workspace_id: str, *, digital_human: bool = False) -> str:
    """工作区里第一个音色(只看有没有这一行),没有就空串。建图时预填哪一把见 `_prefilled_voice_id`。

    模板不可能替用户猜一个音色,而语音节点的音色是必填的。齐了就预填、
    没齐就留空并整段跳过 —— 得到的是一部默片,而不是一个跑到第一镜就失败的工作流。

    `digital_human`:这把嗓子要交给数字人(改口型、说话照片)—— 只挑声明过是谁的(ADR 0028 §5)。
    此前照样预填最早那一把,未声明的克隆音色一进数字人那一步就被拒,而配音的钱已经花了。
    """
    from app.domain.voices.consent import UNDECLARED

    if not workspace_id:
        return ""
    query = select(Voice).where(Voice.workspace_id == workspace_id)
    if digital_human:
        query = query.where(Voice.consent_kind != UNDECLARED)
    voice = db.scalars(query.order_by(Voice.created_at)).first()
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


def _provider_status(db: Session, user_id: str, capability: Any, runtime_status) -> CheckStatus:
    """这项能力(转写、人声分离)**真跑的时候**用得上吗 —— 和 capabilities.choose 同一个先后,只是不起探测:

    - 他定过默认:就看那一家(插件要配好;本机引擎看探测结果);
    - 没定:允许自动用的本机引擎;插件只在这项能力许自动(`auto_single`)且只配好一家时才会被用上。

    此前只要有一家插件配好就说齐 —— 而转写、分离都不许自动用插件(声音交给云端必须是他定过的),真跑时照样没得用。
    """
    from app.domain import capabilities

    plugins = capabilities.plugin_providers(db, user_id, capability)
    chosen = capabilities.default_id(db, user_id, capability)
    plugin = next((one for one in plugins if one.id == chosen), None)
    if plugin is not None:
        return "met" if not plugin.missing and plugin.tool else "missing"
    builtin_ids = {one.id for one in capability.builtins}
    engines = [chosen] if chosen in builtin_ids else [one.id for one in capability.builtins if one.automatic]
    status = _engines_status(runtime_status, [engine.removeprefix("builtin:") for engine in engines])
    if status != "met" and chosen not in builtin_ids and capability.auto_single:
        if len([one for one in plugins if not one.missing]) == 1:
            return "met"
    return status


def _cloned_voice_status(db: Session, workspace_id: str, *, digital_human: bool) -> CheckStatus:
    """模板里配音节点写的是本机克隆引擎:要有一把克隆音色,**而且克隆引擎跑得起来**(此前只看有没有音色行)。
    数字人用的那把还要声明过是谁的。判据只有一份(voices.engine_catalog.cloned_voice_status),配音节点说「用的是
    哪把嗓子」时用的也是它。"""
    from app.domain.voices.engine_catalog import cloned_voice_status

    return cloned_voice_status(db, workspace_id, digital_human=digital_human)  # type: ignore[return-value]


def _prefilled_voice_id(db: Session, workspace_id: str, *, digital_human: bool = False) -> str:
    """建图时预填进配音节点的音色:**只在前置检查说齐了的时候填**(和模板卡片上那一格同一个判据)。

    此前只看有没有音色行(`_first_voice_id`):克隆引擎没装时,卡片上那一格写着缺(用户以为出来的是默片),
    图里却填着音色 —— 整片付完 5 次对话、5 张图、2 段视频,念第一句时才失败。现在没齐就留空:能不配音的模板
    整段跳过旁白,非配不可的(带货口播、稿子口播)运行前就拦在那一格上。
    """
    if _cloned_voice_status(db, workspace_id, digital_human=digital_human) != "met":
        return ""
    return _first_voice_id(db, workspace_id, digital_human=digital_human)


def requirement_statuses(db: Session, *, user_id: str, workspace_id: str) -> dict[str, CheckStatus]:
    """模板前置条件里**能自动查的那几样**,对这个人、这个工作区各是什么状态。

    判据和「用这个模板建一张图」时挑模型的是**同一套**(`_chat_model` / `_reference_image_model` /
    `_shot_video_model` / `_prefilled_voice_id`),引擎和运行时挑提供方同一个先后(`_provider_status`):
    这里说齐了,建出来的图上那一格就是填好的、跑起来用得上;这里说缺,那一格就是空的。两处各写一份判据的话,
    迟早一处说齐、一处留空。
    """
    return {check: status() for check, status in _status_checks(db, user_id=user_id, workspace_id=workspace_id).items()}


def requirement_status(db: Session, *, user_id: str, workspace_id: str, check: str) -> CheckStatus:
    """只查一项(运行前查选中的那个选项要什么时用,见 engine._check_chosen_options)。判据同 requirement_statuses。"""
    return _status_checks(db, user_id=user_id, workspace_id=workspace_id)[check]()


def requirement_problem(db: Session, *, user_id: str, workspace_id: str, check: str) -> str | None:
    """这一项前置条件此刻**缺什么**,一句给人看的话;齐了(或者还没测出来)回 None。

    TikHub 那几项说得出具体缺哪一步(没装、没接、连接卡在哪、工具没勾,见 templates_analysis.tikhub_problem);
    别的检查只有齐 / 不齐,就说那一项没备好。
    """
    if check in (TIKHUB_ACCOUNT, TIKHUB_VIDEO, TIKHUB_COMMENTS):
        return tikhub_problem(db, user_id, check)
    if requirement_status(db, user_id=user_id, workspace_id=workspace_id, check=check) != "missing":
        return None
    return tr("wfWhy_requirementNotMet", check=check)


def _status_checks(db: Session, *, user_id: str, workspace_id: str) -> dict[str, Callable[[], CheckStatus]]:
    """每一项怎么查(到真问的时候才查:运行前只问选中的那一项,不该把引擎探测、音色清单全跑一遍)。"""
    from app.ai.runtime import asr_models, separation_models
    from app.domain import audio_capabilities
    from app.domain.voices import transcription
    from app.domain.workflows.executors.talking import SPEECH_TO_VIDEO, VIDEO_LIPSYNC, talking_models

    def met(found: Any) -> CheckStatus:
        return "met" if found else "missing"

    return {
        CHAT_MODEL: lambda: met(_chat_model(db, user_id).model),
        REFERENCE_IMAGE_MODEL: lambda: met(_reference_image_model(db, user_id, needed=SINGLE_REFERENCE).model),
        MULTI_REFERENCE_IMAGE_MODEL: lambda: met(_reference_image_model(db, user_id, needed=REFERENCE_IMAGES_NEEDED).model),
        REFERENCE_VIDEO_MODEL: lambda: met(_shot_video_model(db, user_id, references=SINGLE_REFERENCE).model),
        MULTI_REFERENCE_VIDEO_MODEL: lambda: met(_shot_video_model(db, user_id).model),
        CLONED_VOICE: lambda: _cloned_voice_status(db, workspace_id, digital_human=False),
        DIGITAL_HUMAN_VOICE: lambda: _cloned_voice_status(db, workspace_id, digital_human=True),
        TRANSCRIPTION_ENGINE: lambda: _provider_status(db, user_id, transcription.CAPABILITY, asr_models.runtime_status),
        SEPARATION_ENGINE: lambda: _provider_status(db, user_id, audio_capabilities.SEPARATION, separation_models.runtime_status),
        SPEECH_VIDEO_MODEL: lambda: met(talking_models(db, SPEECH_TO_VIDEO, user_id)),
        LIPSYNC_VIDEO_MODEL: lambda: met(talking_models(db, VIDEO_LIPSYNC, user_id)),
        TIKHUB_ACCOUNT: lambda: tikhub_status(db, user_id, TIKHUB_ACCOUNT),
        TIKHUB_VIDEO: lambda: tikhub_status(db, user_id, TIKHUB_VIDEO),
        TIKHUB_COMMENTS: lambda: tikhub_status(db, user_id, TIKHUB_COMMENTS),
    }
