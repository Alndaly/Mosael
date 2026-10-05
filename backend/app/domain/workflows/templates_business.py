"""**起点是用户手里已经有的东西**的那几个模板。

和 `templates.py` 里那三个的分别在这里:「从主题到完整视频」是无中生有 —— 让模型编出角色和场景;
另外两个是「一条视频进、一条视频出」。而真实生意里最常见的两种需求都不长这样:

- **一进多出。** 一条口播 / 直播回放 / 访谈,要切成十条竖屏分发。这件事**不需要任何生成模型**,
  转写 + 一次对话 + 截取 + 导出就够了 —— 是所有模板里门槛最低、产出最多的形态,而此前一个都没有。
- **以实物为锚点。** 服装、面料的客户手里有的从来不是主题,是一张平铺图。而且**那件东西不能变** ——
  版型、颜色、纹理、logo 一变就是货不对板。所以这几个模板里,商品图不是"灵感参考",是每一次生成
  都必须带着的**约束**,提示词和负向提示都围着这一条写。

四个模板都刻意避开"必须先装某个引擎"的前置(译配那条要人声分离,劝退过人)。`highlight_shorts`
只要转写 + 对话;另外三个只要对话 + 图像模型,视频是可选的一步。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers import FIRST_FRAME, REFERENCE_IMAGE
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import ModelChoice, _capabilities, _image_plan, _video_plan
from app.domain.workflows.template_requirements import (
    CHAT_MODEL,
    CLONED_VOICE,
    DIGITAL_HUMAN_VOICE,
    REFERENCE_IMAGE_MODEL,
    REFERENCE_VIDEO_MODEL,
    TRANSCRIPTION_ENGINE,
    requirement,
    SPEECH_VIDEO_MODEL,
)

HIGHLIGHT_SHORTS = "highlight_shorts"
PRODUCT_ON_MODEL = "product_on_model"
PRODUCT_PITCH_SHORT = "product_pitch_short"
FABRIC_LOOKBOOK = "fabric_lookbook"
FOOTAGE_MONTAGE = "footage_montage"
TALKING_SCRIPT_VIDEO = "talking_script_video"
PRODUCT_PITCH_PRESENTER = "product_pitch_presenter"

#: 竖屏。短视频平台的默认画幅 —— 横屏素材按 cover 居中裁进来(和剪辑台的「改画幅」同一套)。
VERTICAL = {"width": 1080, "height": 1920}

#: 生成类模板一次最多做多少组。**不是性能上限,是钱的上限**:每一组都是一次付费生成,而跑之前
#: 用户看不到账单。给一个明确的上限,比事后解释为什么扣了这么多好。
MAX_VARIANTS = 12

#: 竖屏在图像 / 视频模型上的画幅写法。
VERTICAL_ASPECT = "9:16"


def _vertical_image_parameters(db: Session | None, image: ModelChoice) -> dict[str, Any]:
    """竖屏成片里的画面按模型尺寸表里 9:16 那一档出。

    不传尺寸的话模型按自己的默认出 —— Seedream 4 是 2048 的方图,铺进竖屏时间线时两侧被裁掉,商品常常就在被裁的
    那一边。认不出的模型(没有尺寸表)不传,交给它自己。
    """
    size = _image_plan(db, image).frame_sizes.get(VERTICAL_ASPECT, "")
    return {"size": size} if size else {}


def _vertical_clip(db: Session | None, video: ModelChoice) -> tuple[int, dict[str, Any], dict[str, str], str]:
    """「把上身图动起来」那一步的时长、参数、循环要给它的几格输入(画幅、分辨率,按尺寸定画幅的模型还有尺寸),
    以及上身图以什么角色交给它。

    都从视频模型的能力表里取:写死 5 秒的话 Veo(只收 4 / 6 / 8)必败;画幅优先竖屏,模型不收竖屏就用它自己的
    默认(或它唯一收的那一档)。时长和参数键和整片生成同一个出处(templates_models._video_plan)。
    """
    plan = _video_plan(db, video)
    capabilities = _capabilities(db, video, "video") or {}
    ratios = [str(one) for one in capabilities.get("aspect_ratios") or ()]
    if not ratios or VERTICAL_ASPECT in ratios:
        aspect = VERTICAL_ASPECT
    else:
        aspect = plan.aspect_ratio if plan.aspect_ratio in ratios else ratios[0]
    inputs = {"aspect_ratio": aspect, "resolution": plan.resolution}
    if plan.sizes:
        #: 按像素尺寸定画幅的模型(万相):尺寸表里竖屏那一档,没有就它自己的默认画幅那一档。
        inputs["video_size"] = plan.sizes.get(VERTICAL_ASPECT) or next(iter(plan.sizes.values()))
    return plan.clip_seconds, dict(plan.parameters or {}), inputs, _still_role(capabilities)


def _still_role(capabilities: dict[str, Any]) -> str:
    """上身图交给视频模型时当什么:能从首帧出片就当首帧(构图、衣服、人都锁死);只会"照参考出片"的模型
    (Seedance 参考生视频、万相 r2v —— 它们不收首帧,或者必须给参考)就当参考图。认不出的模型按首帧,最通用的那条。"""
    keys = set(capabilities.get("parameter_keys") or ())
    required = [set(group) for group in capabilities.get("requires_source") or ()]

    def enough(role: str) -> bool:
        return role in keys and all(role in group for group in required)

    if not keys or enough(FIRST_FRAME):
        return FIRST_FRAME
    return REFERENCE_IMAGE if enough(REFERENCE_IMAGE) else FIRST_FRAME


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _str(description: str = "") -> dict[str, Any]:
    return {"type": "string", **({"description": description} if description else {})}


# --------------------------------------------------------------------------------------
# 1 · 长视频 → 多条竖屏切片
# --------------------------------------------------------------------------------------


def _highlights_schema() -> dict[str, Any]:
    caption = _object(
        {
            # **相对这一条切片的开头**,不是原片时间。切出来的序列从 0 开始,字幕当然也要从 0 开始。
            "start": {"type": "number", "minimum": 0, "description": "相对本条切片开头的秒数"},
            "end": {"type": "number", "minimum": 0},
            "text": _str("这一句字幕,重写过的短句,不是逐字稿原文"),
        },
        ["start", "end", "text"],
    )
    clip = _object(
        {
            "title": _str("这条切片的标题,直接可当发布标题"),
            "hook": _str("前三秒要说的钩子"),
            "start_seconds": {"type": "number", "minimum": 0, "description": "在原片里的起点"},
            "end_seconds": {"type": "number", "minimum": 0, "description": "在原片里的终点"},
            "why": _str("为什么这一段能独立成立"),
            "captions": {"type": "array", "items": caption, "minItems": 1},
        },
        ["title", "hook", "start_seconds", "end_seconds", "why", "captions"],
    )
    return _object(
        {
            #: 切片不花生成费,但每一条是一次本机导出;上限和生成类模板同一个数。可以是 0 条:素材里没有够格的高光时,
            #: 提示词要它「宁可少给」并在 skipped_reason 里说明 —— 此前 minItems 是 1,它只能凑一条出来。
            "clips": {"type": "array", "items": clip, "maxItems": MAX_VARIANTS},
            "skipped_reason": _str("素材里可用高光不足时,说明原因;够用就写空字符串"),
        },
        ["clips", "skipped_reason"],
    )


def highlight_shorts_graph(*, chat: Any) -> dict[str, Any]:
    """一条长视频 → 逐字稿 → 挑高光 → 每条各建一条竖屏序列、截取、配字幕、导出。

    **不生成任何画面,所以零生成成本。** 画面就是原片那一段,只是换了画幅并配上重写过的字幕。

    两个设计选择值得说清:

    - **字幕由模型重写,不是照抄逐字稿。** 竖屏切片的字幕是给静音刷的人看的,逐字稿那种带口头禅
      的长句在小屏上读不完。所以让它顺手输出短句,时间码**相对切片开头**,序列从 0 开始,直接对得上。
    - **每条切片自己一条序列,都在同一个项目里。** 不是在一条时间线上切十刀 —— 那样十条片子共用一个导出,拿不到
      十个文件;也不是十个项目 —— 同一条长视频切出来的东西该放在一处。循环体里各建各的时间线,导出也各是各的。
    """
    system = f"""你是短视频运营和剪辑师。你会收到一条长视频(口播、访谈或直播回放)的带时间码逐字稿，
任务是从里面挑出能**独立成立**的片段：不依赖前文也听得懂、有一个完整的观点或故事、开头三秒就有
抓人的理由。

硬性要求：
- 每条片段的时长必须在给定的上下限之间；片段之间不得重叠；起止时间必须落在素材时长内。
- 起止时间要卡在**句子边界**上，不要从半句话开始或结束。
- 只挑真的够格的。素材里没有那么多高光时，宁可少给几条，并在 skipped_reason 里说明——
  凑数的片段发出去是在消耗账号。最多 {MAX_VARIANTS} 条。
- captions 是**重写过的短句**：每句不超过 18 个字，去掉口头禅和重复，保留原意和原话的语气；
  时间码相对这一条片段的开头（第一句从 0 附近开始），不是原片时间。
- 不要编造素材里没有的内容。

只输出符合 JSON Schema 的对象。"""

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "设定切片规格", "en": "Set the clip rules"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "target_count": 6,
                    "min_seconds": 18,
                    "max_seconds": 58,
                    "audience": "刷竖屏短视频的年轻观众",
                    "width": VERTICAL["width"],
                    "height": VERTICAL["height"],
                    "fps": 30,
                }
            },
        },
        {
            "id": "source_video",
            "type": "asset",
            "name": {"zh": "选择要切的长视频", "en": "Pick the long video"},
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "transcript",
            "type": "transcribe_asset",
            "name": {"zh": "生成带时间码逐字稿", "en": "Transcribe with timecodes"},
            "position": {"x": 650, "y": 260},
            "config": {"asset_id": "{{source_video.asset_id}}"},
        },
        {
            "id": "highlights",
            "type": "llm",
            "name": {"zh": "挑出能独立成立的片段", "en": "Pick the clips that stand alone"},
            "position": {"x": 970, "y": 260},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "precise",
                "system": system,
                "prompt": """素材名称：{{source_video.name}}
素材时长：{{source_video.duration}} 秒
目标观众：{{start.audience}}
想要几条：{{start.target_count}}
每条时长：不短于 {{start.min_seconds}} 秒，不长于 {{start.max_seconds}} 秒

下面是按原视频源时间记录的逐字稿 JSON，每段含 start/end/text：
{{transcript.timed_text}}

请挑出片段并按要求输出。再强调一次：captions 的时间码是**相对每条片段自己的开头**。""",
                "response_format": "json_schema",
                "json_schema_name": "highlight_clips",
                "json_schema": _highlights_schema(),
                "json_schema_strict": "true",
                "temperature": 0.3,
                "max_tokens": 16000,
            },
        },
        {
            "id": "has_clips",
            "type": "condition",
            "name": {"zh": "挑出片段了吗", "en": "Were any clips picked?"},
            "position": {"x": 970, "y": 60},
            "config": {"left": "{{highlights.json.clips}}", "op": "not_empty"},
        },
        {
            "id": "no_clips_notice",
            "type": "notify",
            "name": {"zh": "没有能独立成立的片段", "en": "No clip stands on its own"},
            "position": {"x": 1290, "y": 60},
            "config": {
                "title": "竖屏切片没有切:没挑出够格的片段",
                "body": "{{source_video.name}} 里没有挑出能独立成立的片段。模型的说明:{{highlights.json.skipped_reason}}",
            },
        },
        {
            "id": "clips_project",
            "type": "project_create",
            "name": {"zh": "为这批切片建一个项目", "en": "Create one project for the clips"},
            "position": {"x": 970, "y": 460},
            "config": {"name": "{{source_video.name}} · 竖屏切片"},
        },
        {
            "id": "cut_clips",
            "type": "loop_foreach",
            "name": {"zh": "逐条切成竖屏成片", "en": "Cut each one into a vertical export"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "items": "{{highlights.json.clips}}",
                "inputs": {
                    "project_id": "{{clips_project.project_id}}",
                    "source_asset_id": "{{source_video.asset_id}}",
                    "width": "{{start.width}}",
                    "height": "{{start.height}}",
                    "fps": "{{start.fps}}",
                },
                "body": {
                    "nodes": [
                        {
                            "id": "clip_sequence",
                            "type": "project_sequence_create",
                            "name": {"zh": "为这一条建竖屏时间线", "en": "Create a vertical timeline for this clip"},
                            "position": {"x": 80, "y": 140},
                            "config": {
                                "name": "{{loop.item.title}}",
                                "project_id": "{{input.project_id}}",
                                "width": "{{input.width}}",
                                "height": "{{input.height}}",
                                "fps": "{{input.fps}}",
                            },
                        },
                        {
                            "id": "place_range",
                            "type": "timeline_append",
                            "name": {"zh": "截取原片的这一段", "en": "Take that range from the source"},
                            "position": {"x": 400, "y": 140},
                            "config": {
                                "sequence_id": "{{clip_sequence.sequence_id}}",
                                "asset_id": "{{input.source_asset_id}}",
                                "track_id": "{{clip_sequence.video_track_id}}",
                                "start": "{{loop.item.start_seconds}}",
                                "end": "{{loop.item.end_seconds}}",
                            },
                        },
                        {
                            "id": "burn_captions",
                            "type": "generate_subtitles",
                            "name": {"zh": "铺上重写过的短句字幕", "en": "Lay the rewritten captions"},
                            "position": {"x": 720, "y": 140},
                            "config": {
                                "sequence_id": "{{clip_sequence.sequence_id}}",
                                "segments": "{{loop.item.captions}}",
                                # 时间码已经是相对切片开头的,所以不偏移。
                                "offset": 0,
                                #: 裁到这一条**实际**的终点:终点超出原片时截取被夹到原片末尾,超出去的字幕不该挂在黑屏上。
                                "until": "{{place_range.timeline_end}}",
                            },
                        },
                        {
                            "id": "export_clip",
                            "type": "export_sequence",
                            "name": {"zh": "导出这一条", "en": "Export this clip"},
                            "position": {"x": 1040, "y": 140},
                            "config": {"sequence_id": "{{clip_sequence.sequence_id}}"},
                        },
                    ],
                    "edges": [
                        {"id": "seq_place", "source": "clip_sequence", "target": "place_range"},
                        {"id": "place_caption", "source": "place_range", "target": "burn_captions"},
                        {"id": "caption_export", "source": "burn_captions", "target": "export_clip"},
                    ],
                },
                "output": "{{export_clip.asset_id}}",
                # 导出是本机 ffmpeg,并发开太高只会互相抢 CPU。
                "concurrency": 2,
                #: 「想要几条」不只写进提示词:模型多挑了几条,也只切前这么多条。
                "max_items": "{{start.target_count}}",
                #: 每一条彼此独立:一条的起止时间不对、导出失败,不该让其余几条白切。失败的那几条写进完成通知。
                "on_item_error": "skip",
            },
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "切片完成通知", "en": "Clips ready"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "title": "竖屏切片已导出",
                "body": "{{source_video.name}} 已切出 {{cut_clips.count}} 条竖屏成片,均带字幕。\n{{cut_clips.failure_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付切片与标题", "en": "Hand over the clips and titles"},
            "position": {"x": 1930, "y": 260},
            "config": {
                "values": {
                    "source_asset_id": "{{source_video.asset_id}}",
                    "project_id": "{{clips_project.project_id}}",
                    "clip_asset_ids": "{{cut_clips.results}}",
                    "clip_count": "{{cut_clips.count}}",
                    "plan": "{{highlights.json}}",
                    "skipped_reason": "{{highlights.json.skipped_reason}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_source", "source": "start", "target": "source_video"},
        {"id": "source_transcript", "source": "source_video", "target": "transcript"},
        {"id": "transcript_highlights", "source": "transcript", "target": "highlights"},
        #: 一条都没挑出来就停在这里说清楚(模型的 skipped_reason 写进通知),不建项目。项目在**挑出片段之后**才建:
        #: 此前它和转写并行,转写或那次对话失败时留下一个空项目。
        {"id": "highlights_check", "source": "highlights", "target": "has_clips"},
        {"id": "no_clips", "source": "has_clips", "target": "no_clips_notice", "source_handle": "false"},
        {"id": "highlights_cut", "source": "has_clips", "target": "cut_clips", "source_handle": "true"},
        {"id": "clips_to_project", "source": "has_clips", "target": "clips_project", "source_handle": "true"},
        {"id": "project_cut", "source": "clips_project", "target": "cut_clips"},
        {"id": "cut_notice", "source": "cut_clips", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": HIGHLIGHT_SHORTS, "template_version": 3, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


# --------------------------------------------------------------------------------------
# 2 · 商品图 → 模特上身图与短视频
# --------------------------------------------------------------------------------------

#: 所有以实物为锚点的模板共用的一句话。**这是这几个模板的全部要点** —— 生成的是"这件东西在别处"
#: 而不是"一件像它的东西"。写成常量是因为它要出现在每一个生成提示词里,漏一处就漏一处货不对板。
_KEEP_PRODUCT = (
    "The product in the reference image must be reproduced EXACTLY: identical cut, silhouette, "
    "colour, fabric texture, weave, print scale and placement, stitching, buttons, trims and any "
    "logo or label. Do not redesign, restyle, recolour, resize the print, add or remove details. "
    "Only the wearer, pose, setting and lighting may change."
)

_NEGATIVE_PRODUCT = (
    "different garment, altered pattern, changed colour, distorted print, redesigned collar or "
    "sleeves, extra logos, text, watermark, deformed hands, extra limbs, "
    "phone, smartphone, device frame, screen bezel, mockup, app interface"
)

#: 竖构图**只说构图**。此前写的是「Vertical composition for a phone screen」—— 出图模型把「手机屏幕」画了出来:
#: Seedream 每张都是一台手机、商品在手机屏幕里(真跑截图)。正向提示词里不提设备(说「不要手机」也会招来手机),
#: 设备、边框、界面写进负向提示词(见 _NEGATIVE_PRODUCT)。
_VERTICAL_FRAME = "Vertical 9:16 portrait-orientation photograph, full-bleed: the scene fills the frame edge to edge."


def _lookbook_schema(*, clip_seconds: int | None) -> dict[str, Any]:
    """`clip_seconds` 是视频那一步每段多长;不出视频时为 None,计划里也就不要视频提示词。"""
    properties: dict[str, Any] = {
        "scene_label": _str("这组图的场合名,给人看的,如「通勤 · 清晨街头」"),
        "model_brief": _str("模特设定,英文:年龄段、体型、发型、妆容、神态"),
        "setting": _str("场景与光线,英文"),
        "pose": _str("姿态与取景,英文;要能看清商品的版型"),
        "image_prompt": _str("完整出图提示词,英文,不含机位参数"),
    }
    required = ["scene_label", "model_brief", "setting", "pose", "image_prompt"]
    if clip_seconds is not None:
        properties["video_prompt"] = _str(f"这组的 {clip_seconds} 秒视频提示词,英文:模特的动作节拍与轻微运镜")
        required.append("video_prompt")
    scene = _object(properties, required)
    return _object(
        {
            "product_summary": _str("用一句话复述这件商品的可见特征,证明你看懂了参数"),
            #: 每一组是一次付费出图(带视频时再加一次视频),上限就是钱的上限(见 MAX_VARIANTS)。
            "scenes": {"type": "array", "items": scene, "minItems": 1, "maxItems": MAX_VARIANTS},
            #: 这两段是**直接进笔记的正文**。此前笔记里插的是数组本身,插值把它写成 JSON 原文 ——
            #: 用户打开笔记看到的是一串带引号和方括号的东西。
            "copy_markdown": _str(
                "可直接用的中文卖点短句,Markdown 无序列表,一行一条(以「- 」开头),每条不超过 20 字"
            ),
            "scenes_markdown": _str(
                "给人看的拍摄清单,Markdown 无序列表,每组一行:「- **场合名**:一句中文说明(人物、场景、光线)」"
            ),
        },
        ["product_summary", "scenes", "copy_markdown", "scenes_markdown"],
    )


def product_on_model_graph(
    *, chat: Any, image: Any, video: Any, motion: bool | None = None, db: Session | None = None
) -> dict[str, Any]:
    """一张商品图(平铺图 / 面料图)→ 规划 N 组场景 → 每组出一张模特上身图 →(可选)出一段短视频。

    **商品图贯穿每一次生成**,不是只喂第一次:每一组场景的出图都把它作为 `reference_image` 带上;
    视频那一步只给刚生成的上身图(一般作为 `first_frame`;只会照参考出片的模型作为参考图,见 _still_role)——
    商品就在这张图上,所以"这件衣服"在整条链路上仍然只有一个来源。视频那一步**不再另挂商品图作参考**:同一次生成里首帧和参考图并用,Seedance 2 /
    MiniMax 两组互斥当场拒,Wan / Kling / Seedance 1.x 根本不收参考图 —— 内置视频模型没有一个接得住。

    不让模型"看"商品图去写文案 —— `llm` 节点发不出图片。商品的品类、颜色、材质由用户在参数里写一句,
    模型据此规划场景;像不像由参考图保证,不是由描述保证。

    `motion`:要不要"动起来"那一步。缺省跟着有没有视频模型走;官网那份导出时写 True 而模型留空,由导入的人挑。
    `db` 让视频的时长 / 画幅和出图尺寸读到用户对这个模型的参数声明;没有库的上下文退回内置目录。
    """
    wants_video = bool(getattr(video, "model", "")) if motion is None else motion
    clip_seconds, clip_parameters, clip_inputs, still_role = (
        _vertical_clip(db, video) if wants_video else (None, {}, {}, FIRST_FRAME)
    )

    system = f"""你是服装 / 面料品牌的视觉企划和电商内容负责人。用户会给你一件商品的基本信息和目标人群，
你要规划几组**能直接投放**的模特上身场景。

硬性要求：
- 每一组是一个真实存在的穿着场合，彼此要拉开差别（场合、光线、季节感、构图各不相同），
  不要只换背景色。最多 {MAX_VARIANTS} 组。
- image_prompt 用英文完整描述画面：模特、姿态、取景、环境、光线、氛围。**不要写机位参数**，
  也不要在画面里生成文字、logo 水印或 UI。
- 你**看不到**那张商品图，所以不要描述商品本身的细节——那由参考图保证。你只描述"穿着它的人
  在什么场合、怎么站、光怎么打"。提到商品时用 the product / the garment 指代。
- copy_markdown 是中文卖点短句，可以直接配在图上或发在详情页，不要写成广告腔的空话；
  只从用户给的商品信息里提炼，不要编造面料成分、功能或数据。

只输出符合 JSON Schema 的对象。"""

    body_nodes: list[dict[str, Any]] = [
        {
            "id": "on_model",
            "type": "ai_generate",
            "name": {"zh": "出这一组的模特上身图", "en": "Shoot this scene on a model"},
            "position": {"x": 80, "y": 140},
            "config": {
                "provider": getattr(image, "provider", ""),
                "provider_profile_id": getattr(image, "profile_id", ""),
                "model": getattr(image, "model", ""),
                "kind": "image",
                "prompt": (
                    "{{loop.item.image_prompt}} Model: {{loop.item.model_brief}}. "
                    "Setting: {{loop.item.setting}}. Pose and framing: {{loop.item.pose}}. "
                    f"{_KEEP_PRODUCT} "
                    "The reference image is the product itself, photographed flat. "
                    f"Full-length framing. {_VERTICAL_FRAME} "
                    "Photorealistic commercial fashion photography, no text, no watermark."
                ),
                "negative_prompt": _NEGATIVE_PRODUCT,
                "parameters": _vertical_image_parameters(db, image),
                "source_assets": [f"{{{{input.product_asset_id}}}}:{REFERENCE_IMAGE}"],
            },
        },
        {
            "id": "file_image",
            "type": "asset_update",
            "name": {"zh": "归档这一组的图", "en": "File this scene's image"},
            "position": {"x": 400, "y": 140},
            "config": {
                "asset_ids": "{{on_model.asset_id}}",
                "name": "{{input.product_name}} · {{loop.item.scene_label}}",
                "project_id": "{{input.project_id}}",
            },
        },
    ]
    body_edges = [{"id": "gen_file", "source": "on_model", "target": "file_image"}]
    inputs: dict[str, Any] = {
        "product_asset_id": "{{product_photo.asset_id}}",
        "product_name": "{{start.product_name}}",
        "project_id": "{{shoot_project.project_id}}",
    }

    if wants_video:
        inputs.update(clip_inputs)
        body_nodes += [
            {
                "id": "on_model_clip",
                "type": "ai_generate",
                "name": {"zh": "把这一组动起来", "en": "Put this scene in motion"},
                "position": {"x": 720, "y": 140},
                "config": {
                    "provider": getattr(video, "provider", ""),
                    "provider_profile_id": getattr(video, "profile_id", ""),
                    "model": getattr(video, "model", ""),
                    "kind": "video",
                    "prompt": (
                        "{{loop.item.video_prompt}} "
                        f"{_KEEP_PRODUCT} "
                        "Subtle, natural motion only; the garment must stay readable throughout."
                    ),
                    "negative_prompt": _NEGATIVE_PRODUCT,
                    #: 时长、画幅、分辨率按这个视频模型的能力表挑(见 _vertical_clip),不写死。
                    "parameters": clip_parameters,
                    #: 只给刚出的那张上身图(一般当首帧)—— 视频和静图因此必然是同一套衣服、同一个人。见函数说明。
                    "source_assets": [f"{{{{on_model.asset_id}}}}:{still_role}"],
                },
            },
            {
                "id": "file_clip",
                "type": "asset_update",
                "name": {"zh": "归档这一组的视频", "en": "File this scene's clip"},
                "position": {"x": 1040, "y": 140},
                "config": {
                    "asset_ids": "{{on_model_clip.asset_id}}",
                    "name": "{{input.product_name}} · {{loop.item.scene_label}} · 视频",
                    "project_id": "{{input.project_id}}",
                },
            },
        ]
        body_edges += [
            {"id": "file_clip_gen", "source": "file_image", "target": "on_model_clip"},
            {"id": "clip_file", "source": "on_model_clip", "target": "file_clip"},
        ]

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "描述商品与人群", "en": "Describe the product and the audience"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "product_name": "",
                    #: 留空,不放示例:此前这里写着「品类、颜色、材质、版型,一两句话」,没改就跑的话这句提示
                    #: 原样进了提示词,被当成商品信息。要填什么写在模板卡片的第一步上。
                    "product_brief": "",
                    "audience": "25-35 岁都市通勤女性",
                    "season": "春秋",
                    "brand_tone": "简洁、克制、质感",
                    "scene_count": 4,
                },
                "required_params": ["product_name", "product_brief"],
            },
        },
        {
            "id": "product_photo",
            "type": "asset",
            "name": {"zh": "选择商品平铺图", "en": "Pick the product photo"},
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            #: 只建项目,不建时间线:这个模板交付的是素材(图和视频),不剪片子 —— 此前建的那条空竖屏时间线没人用。
            "id": "shoot_project",
            "type": "project_create",
            "name": {"zh": "建立这次拍摄的项目", "en": "Create a project for this shoot"},
            "position": {"x": 650, "y": 420},
            "config": {"name": "{{start.product_name}} · 上身图"},
        },
        {
            "id": "lookbook_plan",
            "type": "llm",
            "name": {"zh": "规划几组投放场景", "en": "Plan the scenes to shoot"},
            "position": {"x": 650, "y": 120},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "creative",
                "system": system,
                "prompt": """商品名称：{{start.product_name}}
商品信息：{{start.product_brief}}
目标人群：{{start.audience}}
季节：{{start.season}}
品牌调性：{{start.brand_tone}}
要几组场景：{{start.scene_count}}

请规划这几组场景并输出。记住：你看不到商品图，不要描述商品本身。""",
                "response_format": "json_schema",
                "json_schema_name": "product_lookbook_plan",
                "json_schema": _lookbook_schema(clip_seconds=clip_seconds),
                "json_schema_strict": "true",
                "temperature": 0.7,
                "max_tokens": 8000,
            },
        },
        {
            "id": "shoot_scenes",
            "type": "loop_foreach",
            "name": {"zh": "逐组出图", "en": "Shoot each scene"},
            "position": {"x": 970, "y": 260},
            "config": {
                "items": "{{lookbook_plan.json.scenes}}",
                "inputs": inputs,
                "body": {"nodes": body_nodes, "edges": body_edges},
                #: 不写 output:每一组交出它的全部产物(上身图、视频),由下面两步分别取出每一组的图和视频 —— 一组的视频
                #: 没出来,那一组的图照样交(见 loops.loop_foreach)。此前只交上身图,视频要去项目里翻。删掉视频那两个节点,
                #: 图照样取得到(取视频那一步得到的是空的一串)。
                "output": "",
                "concurrency": 2,
                #: 「要几组」是钱的闸门,不只是提示词:模型多规划了几组,也只出前这么多组。
                "max_items": "{{start.scene_count}}",
                #: 每一组彼此独立:一组的视频没出来,其余几组已经付过钱的图和视频照样交付、归档。
                "on_item_error": "skip",
            },
        },
        {
            "id": "scene_images",
            "type": "json_extract",
            "name": {"zh": "取出每一组的上身图", "en": "Collect each scene's image"},
            "position": {"x": 1290, "y": 260},
            "config": {"source": "{{shoot_scenes.results}}", "path": "*.on_model.asset_id"},
        },
        *([{
            "id": "scene_clips",
            "type": "json_extract",
            "name": {"zh": "取出每一组的视频", "en": "Collect each scene's clip"},
            "position": {"x": 1290, "y": 560},
            "config": {"source": "{{shoot_scenes.results}}", "path": "*.on_model_clip.asset_id"},
        }] if wants_video else []),
        {
            "id": "copy_note",
            "type": "note_create",
            "name": {"zh": "把卖点文案存成笔记", "en": "Save the copy as a note"},
            "position": {"x": 1290, "y": 420},
            "config": {
                "title": "{{start.product_name}} · 卖点与场景",
                "markdown": """## 商品

{{lookbook_plan.json.product_summary}}

## 卖点短句

{{lookbook_plan.json.copy_markdown}}

## 拍摄场景

{{lookbook_plan.json.scenes_markdown}}
""",
                "tags": "商品素材",
            },
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "出图完成通知", "en": "Shoot finished"},
            "position": {"x": 1290, "y": 120},
            "config": {
                "title": "模特上身图已生成",
                "body": "{{start.product_name}} 已出 {{shoot_scenes.count}} 组,图和视频都归进了项目,卖点文案已存进笔记。"
                        "\n{{shoot_scenes.failure_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付图与文案", "en": "Hand over the images and the copy"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "values": {
                    "product_asset_id": "{{product_photo.asset_id}}",
                    "image_asset_ids": "{{scene_images.value}}",
                    #: 有视频那一步时,每一组的视频也列出来(视频没出来的那一组不在里面)。
                    **({"video_asset_ids": "{{scene_clips.value}}"} if wants_video else {}),
                    "scene_count": "{{shoot_scenes.count}}",
                    "plan": "{{lookbook_plan.json}}",
                    "copy_note_id": "{{copy_note.note_id}}",
                    #: 视频(有的话)和图都在这个项目里。
                    "project_id": "{{shoot_project.project_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_photo", "source": "start", "target": "product_photo"},
        {"id": "start_plan", "source": "start", "target": "lookbook_plan"},
        #: 项目在规划出来之后才建:此前和那次对话并行,对话失败时留下一个空项目。
        {"id": "plan_project", "source": "lookbook_plan", "target": "shoot_project"},
        {"id": "plan_shoot", "source": "lookbook_plan", "target": "shoot_scenes"},
        {"id": "photo_shoot", "source": "product_photo", "target": "shoot_scenes"},
        {"id": "project_shoot", "source": "shoot_project", "target": "shoot_scenes"},
        {"id": "plan_note", "source": "lookbook_plan", "target": "copy_note"},
        {"id": "shoot_notice", "source": "shoot_scenes", "target": "done_notice"},
        {"id": "shoot_images", "source": "shoot_scenes", "target": "scene_images"},
        *([{"id": "shoot_clips", "source": "shoot_scenes", "target": "scene_clips"},
            {"id": "clips_output", "source": "scene_clips", "target": "output"}] if wants_video else []),
        {"id": "images_output", "source": "scene_images", "target": "output"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
        {"id": "note_output", "source": "copy_note", "target": "output"},
    ]
    return normalize_graph(
        {
            #: v4:竖构图只说构图(此前「for a phone screen」让出图模型画出手机外框)。
            "meta": {"template_id": PRODUCT_ON_MODEL, "template_version": 4, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


# --------------------------------------------------------------------------------------
# 3 · 商品 → 带货口播短视频
# --------------------------------------------------------------------------------------


def _pitch_schema(*, presenter: bool) -> dict[str, Any]:
    """分拍脚本。不出镜的那条**钩子和号召就是首尾两拍**(各有一张画面、一段画外音);出镜的那条由主播另外说,
    所以多两段 `hook_line` / `call_to_action`。不出镜时不要这两段 —— 要了就是让模型白写两句没人念的话。"""
    beat = _object(
        {
            "narration": _str("这一拍要念的口播原文,中文;念出来不超过本拍时长"),
            "seconds": {"type": "number", "minimum": 2, "maximum": 8, "description": "这一拍多长"},
            "visual_prompt": _str("这一拍的画面,英文;商品必须在画面里"),
            "caption": _str("屏幕上的短句,不超过 14 字"),
        },
        ["narration", "seconds", "visual_prompt", "caption"],
    )
    #: 每一拍是一次付费出图,上限就是钱的上限(见 MAX_VARIANTS)。
    beats: dict[str, Any] = {"type": "array", "items": beat, "minItems": 2, "maxItems": MAX_VARIANTS}
    if not presenter:
        beats["description"] = "按时间顺序的各拍:第一拍的 narration 就是前三秒的钩子,最后一拍的 narration 是行动号召"
        return _object({"beats": beats}, ["beats"])
    return _object(
        {
            "hook_line": _str("主播出镜说的开场钩子,中文,念出来不超过 8 秒"),
            "beats": beats,
            "call_to_action": _str("主播出镜说的结尾行动号召,中文,念出来不超过 8 秒"),
        },
        ["hook_line", "beats", "call_to_action"],
    )


def _beat_body(db: Session | None, image: Any, *, engine: str, voice: str, text: Any) -> dict[str, Any]:
    """逐拍的循环体:出这一拍的画面 → 按脚本给的时长铺上视频轨;同时合成这一拍的画外音 → 放在这一拍的开头。

    - 画面是一张图,**用 `end` 定长**(从 0 截到这一拍的 seconds)。此前写的是 `max_duration`,那只会加速、不会
      拉长,而图片进时间线的默认定格是 5 秒 —— 于是每一拍都是 5 秒,和脚本、和画外音都对不上。
    - 画外音落在这一拍**实际**的起点(`beat_on_timeline.timeline_start`,运行时回报),`max_duration` 是这一拍
      实际占的秒数:念得比这一拍长就加速塞进去(最多 1.5 倍),还放不下就裁掉尾巴并发一条通知 —— 不压到下一拍的
      话上,最后一拍也不在成片尾留黑。
    """
    return {
        "nodes": [
            {
                "id": "beat_frame",
                "type": "ai_generate",
                "name": {"zh": "出这一拍的画面", "en": "Paint this beat"},
                "position": {"x": 80, "y": 140},
                "config": {
                    "provider": getattr(image, "provider", ""),
                    "provider_profile_id": getattr(image, "profile_id", ""),
                    "model": getattr(image, "model", ""),
                    "kind": "image",
                    "prompt": (
                        "{{loop.item.visual_prompt}} "
                        f"{_KEEP_PRODUCT} "
                        f"{_VERTICAL_FRAME} Photorealistic, "
                        "no text, no logo overlay, no watermark."
                    ),
                    "negative_prompt": _NEGATIVE_PRODUCT,
                    "parameters": _vertical_image_parameters(db, image),
                    "source_assets": [f"{{{{input.product_asset_id}}}}:{REFERENCE_IMAGE}"],
                },
            },
            {
                #: 每一拍的画面都是付过钱的素材:归进这条短片的项目(此前只铺上时间线,素材库里散着、不在项目里)。
                "id": "file_frame",
                "type": "asset_update",
                "name": {"zh": "归档这一拍的画面", "en": "File this beat's frame"},
                "position": {"x": 400, "y": 0},
                "config": {
                    "asset_ids": "{{beat_frame.asset_id}}",
                    "name": "{{input.product_name}} · {{loop.item.caption}}",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "beat_on_timeline",
                "type": "timeline_append",
                "name": {"zh": "按这一拍的时长铺上去", "en": "Lay it down for this beat's length"},
                "position": {"x": 400, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{beat_frame.asset_id}}",
                    "track_id": "{{input.video_track_id}}",
                    "start": 0,
                    "end": "{{loop.item.seconds}}",
                },
            },
            {
                "id": "has_narration",
                "type": "condition",
                "name": {"zh": "这一拍有画外音吗", "en": "Does this beat have narration?"},
                "position": {"x": 80, "y": 320},
                "config": {"left": "{{loop.item.narration}}", "op": "not_empty"},
            },
            {
                "id": "beat_voice",
                "type": "synthesize_speech",
                "name": {"zh": "念这一拍的画外音", "en": "Voice this beat"},
                "position": {"x": 400, "y": 320},
                "config": {"text": "{{loop.item.narration}}", "engine": engine, "voice": voice},
            },
            {
                "id": "beat_voice_place",
                "type": "timeline_append",
                "name": {"zh": "画外音对齐这一拍开头", "en": "Line the voice up with the beat"},
                "position": {"x": 720, "y": 320},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{beat_voice.asset_id}}",
                    "track_id": "{{input.audio_track_id}}",
                    "at": "{{beat_on_timeline.timeline_start}}",
                    #: 最长就是这一拍画面实际占的秒数;加速到 1.5 倍仍放不下就裁掉尾巴 —— 不压到下一拍,
                    #: 最后一拍也不在成片尾留一截黑屏。
                    "max_duration": "{{beat_on_timeline.duration}}",
                    "trim_overflow": "yes",
                },
            },
            {
                "id": "voice_overflow",
                "type": "condition",
                "name": {"zh": "画外音裁掉了尾巴吗", "en": "Was the voice-over cut short?"},
                "position": {"x": 1040, "y": 320},
                "config": {"left": "{{beat_voice_place.trimmed}}", "op": "gt", "right": "0"},
            },
            {
                "id": "overflow_notice",
                "type": "notify",
                "name": {"zh": "说一声画外音被裁了", "en": "Say the voice-over was cut"},
                "position": {"x": 1360, "y": 320},
                "config": {
                    "title": text("带货短片:有一拍的画外音念不完", "Product short: a beat's voice-over didn't fit"),
                    "body": text(
                        "「{{loop.item.caption}}」那一拍的画外音加速到 1.5 倍仍比画面长 {{beat_voice_place.trimmed}} 秒,"
                        "超出的部分已裁掉。想保住整句,把这一拍的口播改短或把这一拍的时长加长再运行一次。",
                        "The voice-over for the “{{loop.item.caption}}” beat is still {{beat_voice_place.trimmed}} s longer "
                        "than its picture at 1.5× speed, so the rest was cut. To keep the whole line, shorten that beat's "
                        "narration or lengthen the beat and run again.",
                    ),
                },
            },
        ],
        "edges": [
            {"id": "frame_place", "source": "beat_frame", "target": "beat_on_timeline"},
            {"id": "frame_file", "source": "beat_frame", "target": "file_frame"},
            {"id": "place_voice", "source": "beat_on_timeline", "target": "beat_voice_place"},
            {"id": "voice_voice_place", "source": "beat_voice", "target": "beat_voice_place"},
            #: 脚本里某一拍的 narration 是空串(只给画面的一拍)时,画外音那两步整段跳过 —— 此前照样去合成,
            #: 「合成文本不能为空」让整条失败,前面几拍的出图钱白花。
            {"id": "narration_voice", "source": "has_narration", "target": "beat_voice", "source_handle": "true"},
            #: **这一条不能省**(和混剪的 narration_place 同一个道理):「放画外音」的两条入边都是数据边,只剩数据边时
            #: 任一上游跑过就算激活 —— 「铺这一拍」总是跑过的,于是没有画外音时它拿着空素材照跑。带 handle 的边有路由语义。
            {"id": "narration_voice_place", "source": "has_narration", "target": "beat_voice_place", "source_handle": "true"},
            {"id": "voice_overflow_check", "source": "beat_voice_place", "target": "voice_overflow"},
            {"id": "overflow_notify", "source": "voice_overflow", "target": "overflow_notice", "source_handle": "true"},
        ],
    }


#: 带货口播没有能用的克隆音色时念画外音的那把嗓子:微软 Edge 的免费音色,不用配置、不用钥匙。
PITCH_FALLBACK_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"


def _pitch_voice(voice_id: str) -> tuple[str, str]:
    """不出镜那一版用哪把嗓子念:(引擎, 音色)。

    `voice_id` 是建图时预填的克隆音色(templates._prefilled_voice_id:配音库里有、克隆引擎也跑得起来才填)。有就用它;
    没有就用免费的 Edge 音色。此前没有克隆音色这张模板就跑不了:念画外音那一格空着,运行前拦住。用的是哪一把、为什么,
    由配音节点运行时按实际念的那一把说(`voice_note`),不在这里写死 —— 之后在节点里换了音色,说明跟着变。
    """
    from app.domain.voices.speech import CLONE_ENGINE, EDGE_ENGINE

    if voice_id:
        return CLONE_ENGINE, voice_id
    return EDGE_ENGINE, PITCH_FALLBACK_EDGE_VOICE


def product_pitch_short_graph(
    *, chat: Any, image: Any, voice_id: str = "", presenter: bool = False, db: Session | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """商品图 + 几条卖点 → 分拍口播脚本 → 每拍出一张画面、配一段画外音 → 组装 → 字幕 → 导出。

    和「模特上身图」的分别:那个交付的是**素材**(图和视频,你拿去自己用),这个交付的是**一条成片**。

    口播和画面按"拍"对齐:每一拍自己的时长由脚本给出,画面按这个时长铺在时间线上,画外音落在这一拍的开头,
    字幕用这一拍在时间线上的实际起止。不出镜时钩子和号召就是首尾两拍 —— 此前另合成一段「钩子 + 号召」放在 0 秒,
    中间各拍的旁白一句没念、也没有字幕。

    音色直接写在「念这一拍的画外音」上(不经开始节点转一手):那一格是必填的,空着运行前就拦住,而且那里有音色选择器;
    写成 `{{start.voice_id}}` 的话,引用本身算"填了",要等画面都出完、念第一拍时才失败。有克隆音色优先用,没有就用
    免费的 Edge 音色(见 _pitch_voice),用的哪把、为什么,写进完成通知和输出。

    `presenter`:「数字人出镜」(ADR 0028 阶段 3「带货口播升级」)—— 开场钩子和收尾号召换成资产库里的人物**出镜说**
    (`entity_speak`:脸、嗓子、授权声明都是那个人物资产的,没声明的真人当场拒),中间每一拍仍是商品画面,这一拍的口播
    用同一个人物的嗓子念。**先取主播、再写脚本**:主播没挑(运行前拦)或挑的那个已经不在,都在任何一次付费调用之前说清。

    `db` 让出图尺寸读到用户对这个模型的参数声明;没有库的上下文退回内置目录。

    `locale`:图里**给人看的**默认值(新项目的名字、完成通知、念不完的提醒)在建图这一刻定语言,和节点名同一条。
    此前写死中文,官网英文副本里也是中文。
    """
    from app.core.i18n import pick_text

    def text(zh: str, en: str) -> str:
        return pick_text({"zh": zh, "en": en}, locale)

    #: 时长取开始参数(和提示词里那一行同一个数):此前这里写死「20-45 秒」,开始参数填 60 秒时两句话打架。
    system = f"""你是带货短视频的编导。用户给你一件商品和几条卖点，你要写一条约 {{{{start.target_duration_seconds}}}} 秒、
能直接拍的口播脚本，按"拍"拆开。

硬性要求：
- 前三秒必须给出观看理由，不要从"大家好"开始。
- 每一拍的 narration 念出来不能超过这一拍的 seconds：中文按每秒约 4 个字估，宁短勿长。
- visual_prompt 用英文写这一拍的画面，**商品必须出现在画面里**；不要写机位参数，不要在画面里
  生成文字、logo 或水印；也不要把画面写成「手机屏幕里的画面」、不要加设备边框或 App 界面 ——
  成片本来就在手机上看。
- 卖点只能来自用户给的那几条，不要编造功效、成分、资质或数据。
- caption 是屏幕上的短句，不是把 narration 原样抄一遍。
- 最多 {MAX_VARIANTS} 拍：每一拍都要出一张画面。

只输出符合 JSON Schema 的对象。"""
    if presenter:
        system += """

这一条由一位主播**出镜**说开场钩子(hook_line)和结尾号召(call_to_action):这两句是对着镜头说的话,
口语、自然,各自念出来不超过 8 秒;它们**也算在成片时长里**。中间的每一拍是商品画面,narration 是画外音。"""
        timing = "各拍 seconds 之和，加上开场钩子和结尾号召念出来的时长（中文每秒约 4 个字），要接近目标时长。"
    else:
        system += """

这一条没有人出镜:第一拍的 narration 就是开场钩子,最后一拍的 narration 是行动号召 —— 整条片子就是这几拍,
首尾不另加。"""
        timing = "各拍 seconds 之和就是成片时长，要接近目标时长。"

    shoot_inputs: dict[str, Any] = {
        "product_asset_id": "{{product_photo.asset_id}}",
        "product_name": "{{start.product_name}}",
        "project_id": "{{pitch_project.project_id}}",
        "sequence_id": "{{pitch_project.sequence_id}}",
        "video_track_id": "{{pitch_project.video_track_id}}",
        "audio_track_id": "{{pitch_project.audio_track_id}}",
    }
    if presenter:
        shoot_inputs.update({"voice_engine": "{{presenter.voice_engine}}", "voice_id": "{{presenter.voice_id}}"})
        body = _beat_body(db, image, engine="{{input.voice_engine}}", voice="{{input.voice_id}}", text=text)
    else:
        engine, voice = _pitch_voice(voice_id)
        body = _beat_body(db, image, engine=engine, voice=voice, text=text)
    #: 用的是哪把嗓子:第一拍(开场钩子,总有口播)的配音节点运行时说的那一句。出镜版的嗓子是主播自己的,不另说。
    voice_said = "" if presenter else "{{shoot_beats.results.0.beat_voice.voice_note}}"

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填商品与卖点", "en": "Product and selling points"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "product_name": "",
                    #: 留空,不放示例:此前这里写着「一行一条,只写你能负责的卖点」,没改就跑的话这句提示被当成
                    #: 卖点进了脚本。要填什么写在模板卡片的第一步上。
                    "selling_points": "",
                    "audience": "刷竖屏短视频的年轻观众",
                    "target_duration_seconds": 30,
                    "width": VERTICAL["width"],
                    "height": VERTICAL["height"],
                    "fps": 30,
                },
                "required_params": ["product_name", "selling_points"],
            },
        },
        {
            "id": "product_photo",
            "type": "asset",
            "name": {"zh": "选择商品图", "en": "Pick the product photo"},
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "pitch_script",
            "type": "llm",
            "name": {"zh": "写分拍口播脚本", "en": "Write the beat-by-beat script"},
            "position": {"x": 650, "y": 120},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "creative",
                "system": system,
                "prompt": f"""商品名称：{{{{start.product_name}}}}
卖点（只能用这些）：
{{{{start.selling_points}}}}
目标观众：{{{{start.audience}}}}
成片目标时长：{{{{start.target_duration_seconds}}}} 秒

请写出分拍脚本。{timing}""",
                "response_format": "json_schema",
                "json_schema_name": "product_pitch_script",
                "json_schema": _pitch_schema(presenter=presenter),
                "json_schema_strict": "true",
                "temperature": 0.6,
                "max_tokens": 6000,
            },
        },
        {
            #: 脚本写出来先量一遍:每一拍的口播念不念得完。提示词里写了「宁短勿长」,模型照样超(10 秒的口播给 2 秒那一拍
            #: 写了 12 个字,真跑);超了的那几拍交回给模型改短,还长的照旧由「画外音对齐这一拍开头」加速 / 裁剪,完成通知里说明。
            "id": "fit_beats",
            "type": "fit_narration",
            "name": {"zh": "量一遍每拍的口播念不念得完", "en": "Check each beat's narration fits"},
            "position": {"x": 970, "y": 120},
            "config": {
                "items": "{{pitch_script.json.beats}}",
                "text_field": "narration",
                "seconds_field": "seconds",
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
            },
        },
        {
            "id": "pitch_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立竖屏成片时间线", "en": "Create the vertical timeline"},
            "position": {"x": 650, "y": 420},
            "config": {
                "name": text("{{start.product_name}} · 带货短片", "{{start.product_name}} · Product short"),
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "shoot_beats",
            "type": "loop_foreach",
            "name": (
                {"zh": "逐拍出画面、配画外音并上时间线", "en": "Paint, voice and place each beat"}
                if presenter
                else {"zh": "逐拍出画面、配音并上时间线", "en": "Paint, voice and place each beat"}
            ),
            "position": {"x": 970, "y": 260},
            "config": {
                "items": "{{fit_beats.items}}",
                "inputs": shoot_inputs,
                "body": body,
                # 画面要按拍的顺序首尾相接,所以**不能并发** —— 并发的落位顺序是谁先回来谁在前。
                "concurrency": 1,
                #: 不写 output:每一项交出这一拍的全部产物连同这一拍本身,下一步按它的落点和屏幕短句铺字幕。
                "output": "",
            },
        },
        {
            "id": "beat_captions",
            "type": "generate_subtitles",
            "name": {"zh": "按每一拍的落点铺屏幕短句", "en": "Lay each beat's on-screen line"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "sequence_id": "{{pitch_project.sequence_id}}",
                "segments": "{{shoot_beats.results}}",
                "start_field": "beat_on_timeline.timeline_start",
                "end_field": "beat_on_timeline.timeline_end",
                "text_field": "loop.item.caption",
            },
        },
        {
            "id": "export_short",
            "type": "export_sequence",
            "name": {"zh": "导出成片", "en": "Export the short"},
            "position": {"x": 1610, "y": 260},
            "config": {"sequence_id": "{{pitch_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "成片完成通知", "en": "Short is ready"},
            "position": {"x": 1930, "y": 260},
            "config": {
                "title": text("带货短片已导出", "Product short exported"),
                "body": text("{{start.product_name}} 的口播短片已完成,共 {{shoot_beats.count}} 拍。",
                            "The narrated short for {{start.product_name}} is done: {{shoot_beats.count}} beats.")
                + (f"\n{voice_said}" if voice_said else "")
                + "\n{{fit_beats.note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付成片与脚本", "en": "Hand over the short and the script"},
            "position": {"x": 2250, "y": 260},
            "config": {
                "values": {
                    "final_asset_id": "{{export_short.asset_id}}",
                    "script": "{{pitch_script.json}}",
                    "beat_count": "{{shoot_beats.count}}",
                    "caption_count": "{{beat_captions.count}}",
                    "sequence_id": "{{pitch_project.sequence_id}}",
                    #: 这一条用哪把嗓子念的、为什么(见 _pitch_voice)。出镜版的嗓子是主播自己的,不另说。
                    **({"voice": voice_said} if voice_said else {}),
                }
            },
        },
    ]
    if not presenter:
        edges = [
            {"id": "start_photo", "source": "start", "target": "product_photo"},
            {"id": "start_script", "source": "start", "target": "pitch_script"},
            #: 时间线在脚本写出来之后才建:此前和那次对话并行,对话失败时留下一个空项目。
            {"id": "script_project", "source": "pitch_script", "target": "pitch_project"},
            {"id": "script_fit", "source": "pitch_script", "target": "fit_beats"},
            {"id": "fit_shoot", "source": "fit_beats", "target": "shoot_beats"},
            {"id": "project_shoot", "source": "pitch_project", "target": "shoot_beats"},
            {"id": "photo_shoot", "source": "product_photo", "target": "shoot_beats"},
            {"id": "shoot_captions", "source": "shoot_beats", "target": "beat_captions"},
            {"id": "captions_export", "source": "beat_captions", "target": "export_short"},
            {"id": "export_notice", "source": "export_short", "target": "done_notice"},
            {"id": "notice_output", "source": "done_notice", "target": "output"},
        ]
        return normalize_graph(
            {
                #: v4:没有能用的克隆音色时用免费的 Edge 音色念(此前那一格空着,运行前拦住、跑不了)。
                #: v5:竖构图只说构图(此前「for a phone screen」让出图模型画出手机外框)。
                "meta": {"template_id": PRODUCT_PITCH_SHORT, "template_version": 5, "source": "official"},
                "nodes": nodes,
                "edges": edges,
            },
            node_types=NODE_TYPES,
        )
    return _with_presenter(nodes, text)


# --------------------------------------------------------------------------------------
# 4 · 面料 → 应用场景图 + 规格卡
# --------------------------------------------------------------------------------------


def _fabric_schema() -> dict[str, Any]:
    application = _object(
        {
            "product_type": _str("做成什么,中文,如「窗帘」「单人沙发」「长袖衬衫」"),
            "why_it_suits": _str("为什么这块料适合做它,中文,一句话"),
            "image_prompt": _str("完整出图提示词,英文:成品在真实空间里的样子"),
        },
        ["product_type", "why_it_suits", "image_prompt"],
    )
    return _object(
        {
            "spec_markdown": _str("规格卡正文,Markdown,中文;只写用户给出的参数,不要编造"),
            #: 每一种是一次付费出图,上限就是钱的上限(见 MAX_VARIANTS)。
            "applications": {"type": "array", "items": application, "minItems": 1, "maxItems": MAX_VARIANTS},
            #: 规格页「适合做什么」那一节的正文。此前插的是 applications 数组本身,插值把它写成 JSON 原文 ——
            #: 发给客户的那一页上是一串带引号和方括号的东西。
            "applications_markdown": _str(
                "给客户看的应用清单,Markdown 无序列表,每种一行:「- **做成什么**:为什么这块料适合做它」"
            ),
            "care_notes": _str("养护与工艺提示,中文;不确定的写「需与工厂确认」"),
        },
        ["spec_markdown", "applications", "applications_markdown", "care_notes"],
    )


def fabric_lookbook_graph(*, chat: Any, image: Any) -> dict[str, Any]:
    """一块面料 → 规划几种应用 → 每种出一张成品效果图 → 连同规格卡存成一页笔记。

    这是**给客户看的提案**,不是给平台发的内容:布料商最常被问的一句话是"这块布做成 X 长什么样",
    而他手里只有一张面料特写。所以交付物是「效果图 + 一页可以直接发出去的规格说明」。

    规格卡**只复述用户给的参数**。成分、克重、幅宽、缩率这些是要负责任的数字,编一个出来比不写更糟 ——
    提示词里写死了这一条,拿不准的一律写「需与工厂确认」。
    """
    system = f"""你是面料商的技术销售和陈列企划。客户给你一块面料的参数，你要做两件事：

1. 规划几种这块料**真的适合**的应用（家纺、服装、软装等），每种给一张成品效果图的英文提示词，
   最多 {MAX_VARIANTS} 种。
   效果图要把成品放在真实空间里，让人一眼看出垂坠感、厚度和纹理，不是平铺特写。
2. 写一页规格卡。

硬性要求：
- 规格卡**只能复述用户给出的参数**。成分、克重、幅宽、缩率、色牢度这些是要负责任的数字，
  用户没给就不要写；确实需要但没有的，写「需与工厂确认」。
- 不要承诺任何认证、检测结论或环保资质。
- image_prompt 用英文，不要写机位参数，不要在画面里生成文字或水印。
- 你**看不到**那块面料的图，所以不要描述它的花型和颜色细节——那由参考图保证。

只输出符合 JSON Schema 的对象。"""

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填面料参数", "en": "Fabric specs"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    #: 参数全部留空,不放示例:此前成分一格写着「成分,如 60% 棉 40% 亚麻」,没改就跑的话规格卡上
                    #: 就印着 60% 棉 —— 而规格卡是「只复述用户给的参数」的那一页。没填的由提示词落成「需与工厂确认」。
                    "fabric_name": "",
                    "composition": "",
                    "weight_gsm": "",
                    "width_cm": "",
                    "hand_feel": "",
                    "target_client": "家纺采购 / 服装品牌",
                    "application_count": 4,
                },
                "required_params": ["fabric_name"],
            },
        },
        {
            "id": "fabric_photo",
            "type": "asset",
            "name": {"zh": "选择面料图", "en": "Pick the fabric photo"},
            "position": {"x": 330, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "fabric_plan",
            "type": "llm",
            "name": {"zh": "规划应用与规格卡", "en": "Plan the applications and the spec sheet"},
            "position": {"x": 650, "y": 260},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "precise",
                "system": system,
                "prompt": """面料名称：{{start.fabric_name}}
成分：{{start.composition}}
克重：{{start.weight_gsm}}
幅宽：{{start.width_cm}}
手感与垂坠：{{start.hand_feel}}
客户类型：{{start.target_client}}
要几种应用：{{start.application_count}}

请输出应用规划与规格卡。没给的参数不要编。""",
                "response_format": "json_schema",
                "json_schema_name": "fabric_lookbook_plan",
                "json_schema": _fabric_schema(),
                "json_schema_strict": "true",
                "temperature": 0.4,
                "max_tokens": 8000,
            },
        },
        {
            "id": "render_applications",
            "type": "loop_foreach",
            "name": {"zh": "逐种出成品效果图", "en": "Render each application"},
            "position": {"x": 970, "y": 260},
            "config": {
                "items": "{{fabric_plan.json.applications}}",
                "inputs": {
                    "fabric_asset_id": "{{fabric_photo.asset_id}}",
                    "fabric_name": "{{start.fabric_name}}",
                },
                "body": {
                    "nodes": [
                        {
                            "id": "application_shot",
                            "type": "ai_generate",
                            "name": {"zh": "出这一种的效果图", "en": "Render this application"},
                            "position": {"x": 80, "y": 140},
                            "config": {
                                "provider": getattr(image, "provider", ""),
                                "provider_profile_id": getattr(image, "profile_id", ""),
                                "model": getattr(image, "model", ""),
                                "kind": "image",
                                "prompt": (
                                    "{{loop.item.image_prompt}} "
                                    "The reference image is the actual fabric, photographed flat. "
                                    "Reproduce its weave, texture, colour, sheen and print scale EXACTLY on the "
                                    "finished product; do not restyle or recolour it. "
                                    "Photorealistic interior or product photography, natural light, "
                                    "no text, no watermark."
                                ),
                                "negative_prompt": (
                                    "different fabric, altered weave, changed colour, distorted pattern scale, "
                                    "text, watermark, plastic looking material"
                                ),
                                "parameters": {},
                                "source_assets": [f"{{{{input.fabric_asset_id}}}}:{REFERENCE_IMAGE}"],
                            },
                        },
                        {
                            "id": "tag_shot",
                            "type": "asset_tag",
                            "name": {"zh": "打上面料标签", "en": "Tag it with the fabric"},
                            "position": {"x": 400, "y": 140},
                            "config": {
                                "asset_ids": "{{application_shot.asset_id}}",
                                "tags": "面料提案,{{input.fabric_name}}",
                                "mode": "add",
                            },
                        },
                    ],
                    "edges": [{"id": "shot_tag", "source": "application_shot", "target": "tag_shot"}],
                },
                "output": "{{application_shot.asset_id}}",
                "concurrency": 2,
                #: 「要几种应用」是钱的闸门:模型多规划了几种,也只出前这么多张。
                "max_items": "{{start.application_count}}",
                #: 每一种彼此独立:一张没出来,其余几张照样进提案。
                "on_item_error": "skip",
            },
        },
        {
            "id": "spec_note",
            "type": "note_create",
            "name": {"zh": "生成可直接发客户的规格页", "en": "Write the spec sheet to send"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "title": "{{start.fabric_name}} · 规格与应用提案",
                "markdown": """{{fabric_plan.json.spec_markdown}}

## 适合做什么

{{fabric_plan.json.applications_markdown}}

## 养护与工艺

{{fabric_plan.json.care_notes}}

---

效果图为 AI 依据本面料实拍图生成,用于沟通版型与观感;**成分、克重、幅宽、色牢度以工厂实测为准**。
""",
                "tags": "面料提案",
            },
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "提案完成通知", "en": "Proposal ready"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "title": "面料提案已生成",
                "body": "{{start.fabric_name}} 已出 {{render_applications.count}} 张应用效果图,规格页已存进笔记。"
                        "\n{{render_applications.failure_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付效果图与规格页", "en": "Hand over the renders and the spec sheet"},
            "position": {"x": 1930, "y": 260},
            "config": {
                "values": {
                    "fabric_asset_id": "{{fabric_photo.asset_id}}",
                    "render_asset_ids": "{{render_applications.results}}",
                    "render_count": "{{render_applications.count}}",
                    "plan": "{{fabric_plan.json}}",
                    "spec_note_id": "{{spec_note.note_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_photo", "source": "start", "target": "fabric_photo"},
        {"id": "start_plan", "source": "start", "target": "fabric_plan"},
        {"id": "photo_render", "source": "fabric_photo", "target": "render_applications"},
        {"id": "plan_render", "source": "fabric_plan", "target": "render_applications"},
        {"id": "plan_note", "source": "fabric_plan", "target": "spec_note"},
        {"id": "render_notice", "source": "render_applications", "target": "done_notice"},
        {"id": "note_notice", "source": "spec_note", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": FABRIC_LOOKBOOK, "template_version": 3, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


def talking_script_video_graph(*, voice_id: str = "") -> dict[str, Any]:
    """稿子 → 数字人口播(ADR 0028 阶段 3):一张正脸 + 一段稿子 → 分段配音 → 逐段说话照片 → 接上时间线 + 字幕 → 导出。

    说话照片一次只收一小段音频(wan2.2-s2v 20 秒),长稿由「长稿分段配音」按句切、按实测时长分组;每段都从同一张脸
    开始,接缝在句子之间。字幕用稿子加配音的实测时长,不再转写。**「让它说话」上的授权确认留空** —— 这张脸是谁的、
    是否取得同意,由跑的人自己选,模板不替他选。

    **稿子和音色直接写在「长稿分段配音」上**,不经开始节点转一手:那两格是必填的,空着运行前就拦住(音色那格还有
    选择器)。此前稿子是开始节点里的一句「把要说的话贴在这里…」—— 没改就跑,这句提示被当成稿子念了出来;音色写成
    `{{start.voice_id}}`,引用本身算"填了",空着也要等跑起来才失败。
    """
    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填稿子", "en": "The script"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "title": "数字人口播",
                    "width": VERTICAL["width"],
                    "height": VERTICAL["height"],
                    "fps": 25,
                }
            },
        },
        {
            "id": "face",
            "type": "asset",
            "name": {"zh": "选一张正脸", "en": "Pick a portrait"},
            "position": {"x": 330, "y": 120},
            "config": {"asset_id": ""},
        },
        {
            "id": "voicing",
            "type": "talking_segments",
            "name": {"zh": "长稿分段配音", "en": "Voice the script in segments"},
            "position": {"x": 330, "y": 400},
            #: 稿子留空,由跑的人贴进来;音色预填工作区里第一个克隆音色(没有就空着,运行前拦住)。
            "config": {"text": "", "engine": "builtin:clone", "voice": voice_id, "model": ""},
        },
        {
            "id": "project",
            "type": "project_sequence_create",
            "name": {"zh": "建立口播时间线", "en": "Create the timeline"},
            "position": {"x": 650, "y": 400},
            "config": {
                "name": "{{start.title}}",
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "speak_segments",
            "type": "loop_foreach",
            "name": {"zh": "逐段让它说话并接上时间线", "en": "Make each segment speak onto the timeline"},
            "position": {"x": 970, "y": 260},
            "config": {
                "items": "{{voicing.segments}}",
                "inputs": {
                    "face_asset_id": "{{face.asset_id}}",
                    "sequence_id": "{{project.sequence_id}}",
                    "video_track_id": "{{project.video_track_id}}",
                },
                "body": {
                    "nodes": [
                        {
                            "id": "speak",
                            "type": "image_speak",
                            "name": {"zh": "这一段说话照片", "en": "Speaking photo for this segment"},
                            "position": {"x": 80, "y": 140},
                            "config": {
                                "asset_id": "{{input.face_asset_id}}",
                                "audio_asset_id": "{{loop.item.audio_asset_id}}",
                                #: 用分段时挑定的那个模型:段是按它的音频上限切的。留空的话这里再挑一次,
                                #: 可能挑到上限更短的另一个,整段被拒。
                                "model": "{{loop.item.model}}",
                                #: 留空:授权要跑的人自己确认(见函数说明)。
                                "consent": "",
                            },
                        },
                        {
                            "id": "place",
                            "type": "timeline_append",
                            "name": {"zh": "接到上一段后面", "en": "Place it after the previous one"},
                            "position": {"x": 400, "y": 140},
                            "config": {
                                "sequence_id": "{{input.sequence_id}}",
                                "asset_id": "{{speak.asset_id}}",
                                "track_id": "{{input.video_track_id}}",
                            },
                        },
                    ],
                    "edges": [{"id": "speak_place", "source": "speak", "target": "place"}],
                },
                #: 按段的顺序首尾相接,**不能并发** —— 并发的落位顺序是谁先回来谁在前。
                "concurrency": 1,
                "output": "{{place.clip_id}}",
            },
        },
        {
            "id": "captions",
            "type": "generate_subtitles",
            "name": {"zh": "按配音时间铺字幕", "en": "Caption from the voicing times"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "sequence_id": "{{project.sequence_id}}",
                "segments": "{{voicing.cues}}",
                "start_field": "start",
                "end_field": "end",
                "text_field": "text",
            },
        },
        {
            "id": "export_video",
            "type": "export_sequence",
            "name": {"zh": "导出成片", "en": "Export the video"},
            "position": {"x": 1610, "y": 260},
            "config": {"sequence_id": "{{project.sequence_id}}"},
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付成片", "en": "Hand over the video"},
            "position": {"x": 1930, "y": 260},
            "config": {
                "values": {
                    "final_asset_id": "{{export_video.asset_id}}",
                    "segment_clip_ids": "{{speak_segments.results}}",
                    "sequence_id": "{{project.sequence_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_face", "source": "start", "target": "face"},
        {"id": "start_voicing", "source": "start", "target": "voicing"},
        {"id": "start_project", "source": "start", "target": "project"},
        {"id": "voicing_speak", "source": "voicing", "target": "speak_segments"},
        {"id": "face_speak", "source": "face", "target": "speak_segments"},
        {"id": "project_speak", "source": "project", "target": "speak_segments"},
        {"id": "speak_captions", "source": "speak_segments", "target": "captions"},
        {"id": "captions_export", "source": "captions", "target": "export_video"},
        {"id": "export_output", "source": "export_video", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": TALKING_SCRIPT_VIDEO, "template_version": 3, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


def _with_presenter(nodes: list[dict[str, Any]], text: Any) -> dict[str, Any]:
    """带货口播换成「数字人出镜」(见 product_pitch_short_graph 的 `presenter`):加一个挑主播的节点、开场和收尾两段
    出镜说话;逐拍的循环体已经按主播的嗓子配好(见 _beat_body)。

    时间线上的顺序是**开场 → 各拍 → 收尾**,靠连线定先后(接到时间线是往轨尾接的)。出镜那两段自带声音;
    每一拍的画外音放在音频轨上、对齐这一拍的开头。

    **脚本和项目都挂在主播之后**:「挑一位主播」是运行前必填的(entity_get 的点名 / 按名字找二选一),而挑的那个
    人物要是已经删了,取主播这一步就失败 —— 在写脚本那次计费的对话之前,也不会留下一个空项目。
    """
    talk = [
        {
            "id": "presenter",
            "type": "entity_get",
            "name": {"zh": "挑一位主播(资产库里的人物)", "en": "Pick the presenter (a character from the asset library)"},
            "position": {"x": 330, "y": 520},
            #: 留空,由跑的人挑:脸、嗓子和授权声明都跟着这个人物走。
            "config": {"entity_id": "", "kind": "character"},
        },
        {
            "id": "has_hook",
            "type": "condition",
            "name": {"zh": "开场有话要说吗", "en": "Is there a hook line?"},
            "position": {"x": 650, "y": 520},
            "config": {"left": "{{pitch_script.json.hook_line}}", "op": "not_empty"},
        },
        {
            "id": "hook_talk",
            "type": "entity_speak",
            "name": {"zh": "主播出镜说开场", "en": "Presenter speaks the hook"},
            "position": {"x": 650, "y": 620},
            "config": {"entity_id": "{{presenter.entity_id}}", "text": "{{pitch_script.json.hook_line}}", "model": ""},
        },
        {
            "id": "hook_place",
            "type": "timeline_append",
            "name": {"zh": "开场放在最前面", "en": "Put the hook first"},
            "position": {"x": 970, "y": 620},
            "config": {"sequence_id": "{{pitch_project.sequence_id}}", "asset_id": "{{hook_talk.asset_id}}",
                       "track_id": "{{pitch_project.video_track_id}}"},
        },
        {
            "id": "has_cta",
            "type": "condition",
            "name": {"zh": "收尾有话要说吗", "en": "Is there a call to action?"},
            "position": {"x": 650, "y": 720},
            "config": {"left": "{{pitch_script.json.call_to_action}}", "op": "not_empty"},
        },
        {
            "id": "cta_talk",
            "type": "entity_speak",
            "name": {"zh": "主播出镜说收尾", "en": "Presenter speaks the call to action"},
            "position": {"x": 650, "y": 800},
            "config": {"entity_id": "{{presenter.entity_id}}", "text": "{{pitch_script.json.call_to_action}}", "model": ""},
        },
        {
            #: 主播能不能出镜,在写脚本那次计费的对话**之前**问:没有音色、没有图的话,开场那一段要等脚本写完、
            #: 画面出完才被拒(entity_speak 里的检查)。这两样从取主播那一步的产物里就看得出来,不花钱。
            "id": "presenter_has_voice",
            "type": "condition",
            "name": {"zh": "主播有音色吗", "en": "Does the presenter have a voice?"},
            "position": {"x": 330, "y": 700},
            "config": {"left": "{{presenter.voice_id}}", "op": "not_empty"},
        },
        {
            "id": "presenter_has_face",
            "type": "condition",
            "name": {"zh": "主播有图吗", "en": "Does the presenter have an image?"},
            "position": {"x": 330, "y": 860},
            "config": {"left": "{{presenter.asset_ids}}", "op": "not_empty"},
        },
        {
            "id": "presenter_voice_notice",
            "type": "notify",
            "name": {"zh": "主播还没有音色", "en": "The presenter has no voice yet"},
            "position": {"x": 40, "y": 860},
            "config": {
                "title": text("带货短片没有开始:主播还没有音色", "Product short not started: the presenter has no voice"),
                "body": text(
                    "「{{presenter.name}}」还没有配音色。在资产库里给它配一把(克隆音色要声明是谁的),再运行一次。"
                    "还没花任何钱。",
                    "“{{presenter.name}}” has no voice yet. Give it one in the asset library (a cloned voice needs a "
                    "consent declaration) and run again. Nothing has been spent.",
                ),
            },
        },
        {
            "id": "presenter_face_notice",
            "type": "notify",
            "name": {"zh": "主播还没有图", "en": "The presenter has no image yet"},
            "position": {"x": 40, "y": 1020},
            "config": {
                "title": text("带货短片没有开始:主播还没有图", "Product short not started: the presenter has no image"),
                "body": text(
                    "「{{presenter.name}}」还没有一张正面图。在资产库里给它加一张(或先画一张),再运行一次。还没花任何钱。",
                    "“{{presenter.name}}” has no front image yet. Add one in the asset library (or draw one first) and run "
                    "again. Nothing has been spent.",
                ),
            },
        },
        {
            #: 收尾那段要接在各拍**之后**,而「排在各拍之后」的那条边没有路由语义 —— 直接连到「收尾接在最后」的话,
            #: 各拍一跑完它就算激活,没有收尾那段时拿着空素材照跑。所以先在各拍之后问一句「收尾那段出来了吗」。
            "id": "cta_spoken",
            "type": "condition",
            "name": {"zh": "收尾那段出来了吗", "en": "Did the call to action come out?"},
            "position": {"x": 970, "y": 800},
            "config": {"left": "{{cta_talk.asset_id}}", "op": "not_empty"},
        },
        {
            "id": "cta_place",
            "type": "timeline_append",
            "name": {"zh": "收尾接在最后", "en": "Put the call to action last"},
            "position": {"x": 1290, "y": 800},
            "config": {"sequence_id": "{{pitch_project.sequence_id}}", "asset_id": "{{cta_talk.asset_id}}",
                       "track_id": "{{pitch_project.video_track_id}}"},
        },
    ]
    shoot = next(node for node in nodes if node["id"] == "shoot_beats")
    kept = list(nodes)
    kept[kept.index(shoot):kept.index(shoot)] = talk
    output = next(node for node in kept if node["id"] == "output")
    output["config"]["values"].update({"hook_asset_id": "{{hook_talk.asset_id}}", "cta_asset_id": "{{cta_talk.asset_id}}"})
    edges = [
        {"id": "start_photo", "source": "start", "target": "product_photo"},
        {"id": "start_presenter", "source": "start", "target": "presenter"},
        #: 先有主播,再写脚本、建项目(见函数说明)。
        #: 主播有音色、有图,才写脚本(脚本写出来才建项目);缺哪样就发一条通知停在这里(一分钱没花)。
        {"id": "presenter_voice_check", "source": "presenter", "target": "presenter_has_voice"},
        {"id": "presenter_voice_ok", "source": "presenter_has_voice", "target": "presenter_has_face", "source_handle": "true"},
        {"id": "presenter_voice_missing", "source": "presenter_has_voice", "target": "presenter_voice_notice",
         "source_handle": "false"},
        {"id": "presenter_face_missing", "source": "presenter_has_face", "target": "presenter_face_notice",
         "source_handle": "false"},
        {"id": "presenter_script", "source": "presenter_has_face", "target": "pitch_script", "source_handle": "true"},
        {"id": "script_project", "source": "pitch_script", "target": "pitch_project"},
        #: 开场 / 收尾那句是空串时,出镜那两步整段跳过(此前照样去生成,空稿子当场被拒,出图的钱白花)。
        #: 「说话」和「接上时间线」**都**挂在条件的「真」出口上:它们其余的入边都是数据边,只剩数据边时任一上游跑过
        #: 就算激活 —— 建项目那一步总是跑过的。
        {"id": "presenter_hook", "source": "presenter", "target": "hook_talk"},
        {"id": "script_has_hook", "source": "pitch_script", "target": "has_hook"},
        {"id": "hook_said", "source": "has_hook", "target": "hook_talk", "source_handle": "true"},
        {"id": "presenter_cta", "source": "presenter", "target": "cta_talk"},
        {"id": "script_has_cta", "source": "pitch_script", "target": "has_cta"},
        {"id": "cta_said", "source": "has_cta", "target": "cta_talk", "source_handle": "true"},
        #: 先后:开场接上 → 各拍 → 收尾(都是往视频轨尾接)。
        {"id": "hook_place_edge", "source": "hook_talk", "target": "hook_place"},
        {"id": "project_hook", "source": "pitch_project", "target": "hook_place"},
        {"id": "hook_place_gate", "source": "has_hook", "target": "hook_place", "source_handle": "true"},
        {"id": "hook_then_beats", "source": "hook_place", "target": "shoot_beats"},
        #: 逐拍只挂在脚本(和开场)之后:商品图、主播是它引用的值(引用即依赖,照样等它们),但不能让它们
        #: 把逐拍激活 —— 主播缺音色停下时,脚本没写,逐拍也不该跑。
        {"id": "script_fit", "source": "pitch_script", "target": "fit_beats"},
        {"id": "fit_shoot", "source": "fit_beats", "target": "shoot_beats"},
        {"id": "beats_then_cta", "source": "shoot_beats", "target": "cta_spoken"},
        {"id": "cta_place_edge", "source": "cta_talk", "target": "cta_place"},
        {"id": "cta_place_gate", "source": "cta_spoken", "target": "cta_place", "source_handle": "true"},
        #: 字幕排在收尾接上**之后**:两步改的是同一条时间线,同时提交时后到的那个撞上版本号。
        {"id": "cta_captions", "source": "cta_place", "target": "beat_captions"},
        {"id": "shoot_captions", "source": "shoot_beats", "target": "beat_captions"},
        {"id": "captions_export", "source": "beat_captions", "target": "export_short"},
        {"id": "export_notice", "source": "export_short", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            #: v5:竖构图只说构图(此前「for a phone screen」让出图模型画出手机外框)。
            "meta": {"template_id": PRODUCT_PITCH_PRESENTER, "template_version": 5, "source": "official"},
            "nodes": kept,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


#: 模板库里这四条的卡片。和 `TEMPLATE_CATALOG` 里那三条同一个形状,由 templates.py 拼在一起 ——
#: 卡片和图分开写是因为**卡片要先于图存在**:用户是照着 requires 判断自己能不能跑的。
BUSINESS_TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": HIGHLIGHT_SHORTS,
        "name": {"zh": "长视频切多条竖屏", "en": "Long video into vertical clips"},
        "summary": {
            "zh": "把一条口播、访谈或直播回放转成逐字稿,挑出能独立成立的片段(最多 12 条),每条在同一个项目里各建一条竖屏时间线、截取原片那一段、配上重写过的短句字幕并导出。不生成任何画面,所以除了转写和一次对话之外不花生成费用。",
            "en": "Transcribe a talk, interview or stream recording, pick the passages that stand on their own (up to 12), then give each one its own vertical timeline in a single project, take that range from the source, lay rewritten short captions on it and export. No image or video generation, so nothing is billed beyond the transcription and one chat call.",
        },
        "requires": [
            requirement(TRANSCRIPTION_ENGINE, zh="可用的转写引擎", en="Available transcription engine"),
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(None, zh="一条有人说话的长视频", en="A long video with speech"),
        ],
        "stages": {
            "zh": ["选择长视频", "生成带时间码逐字稿", "挑出能独立成立的片段", "逐条建竖屏时间线并截取", "配重写过的字幕", "逐条导出"],
            "en": ["Pick the long video", "Transcribe with timecodes", "Pick the passages that stand alone", "Give each its own vertical timeline", "Lay the rewritten captions", "Export each one"],
        },
    },
    {
        "id": PRODUCT_ON_MODEL,
        "name": {"zh": "商品图 → 模特上身图与短视频", "en": "Product photo into on-model shots"},
        "summary": {
            "zh": "给一张平铺图或面料图,规划几组投放场景(最多 12 组),每组出一张竖幅模特上身图;视频模型可用时再以这张图为首帧把每一组动起来。商品图贯穿每一次生成 —— 版型、颜色、纹理、logo 都以它为准,不是照描述重画。图和视频都归进一个项目,卖点文案一并存成笔记。每一组是一次付费出图(带视频再加一次视频生成)。",
            "en": "From one flat-lay or fabric photo, plan a few sellable scenes (up to 12) and shoot a portrait on-model image for each; where a video model is available, put every scene in motion with that image as its first frame. The product photo is carried into every generation — cut, colour, texture and logo come from it, not from a description. Images and clips are filed into one project and the copy lines are saved as a note. Each scene is one paid image generation (plus one video generation with motion).",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(
                REFERENCE_IMAGE_MODEL,
                zh="能带参考图出图的图像模型(如 Seedream 4)",
                en="Image model that takes reference images (e.g. Seedream 4)",
            ),
            requirement(None, zh="一张商品平铺图或面料图", en="A flat-lay or fabric photo"),
            requirement(
                REFERENCE_VIDEO_MODEL,
                zh="短视频可选:支持首帧的视频模型",
                en="Optional motion: a video model that takes a first frame",
                optional=True,
            ),
        ],
        "stages": {
            "zh": ["描述商品与人群(商品名和一两句商品信息:品类、颜色、材质、版型)", "选择商品图", "规划几组投放场景", "逐组出模特上身图", "可选:逐组出短视频", "卖点文案存成笔记"],
            "en": ["Describe the product and audience (its name, plus a line or two on category, colour, material and cut)", "Pick the product photo",
                   "Plan the scenes", "Shoot each scene on a model", "Optional: put each scene in motion", "Save the copy as a note"],
        },
        #: 只给官网下载的那一份(见 scripts/sync-website-workflows.py):它按「带视频」导出、模型留空,应用里建的这一份
        #: 会按有没有视频模型自动取舍,用不着这句。
        "download_note": {
            "zh": "这一份带着「把这一组动起来」:没有视频模型的话,导入后在画布上删掉「把这一组动起来」和「归档这一组的视频」"
                  "两个节点就只出图 —— 循环交出的是上身图,不依赖它们。",
            "en": " This copy includes “Put this scene in motion”. Without a video model, delete “Put this scene in motion” and "
                  "“File this scene's clip” on the canvas after importing and it shoots stills only — the loop hands over the "
                  "on-model images and doesn't depend on those two.",
        },
    },
    {
        "id": PRODUCT_PITCH_SHORT,
        "name": {"zh": "商品 → 带货口播短视频", "en": "Product into a narrated short"},
        "summary": {
            "zh": "给一张商品图和几条卖点,写一条分拍的口播脚本(第一拍是钩子、最后一拍是行动号召,最多 12 拍),每一拍出一张带商品的竖幅画面、按这一拍的时长铺上时间线,念这一拍的画外音、对齐这一拍的开头(有克隆音色优先用,没有就用免费的 Edge 音色),再铺上屏幕短句,导出竖屏成片。没有人出镜。卖点只用你给的那几条,不编功效和数据。",
            "en": "From a product photo and a few selling points, write a beat-by-beat script (the first beat is the hook, the last the call to action, up to 12 beats), paint one portrait frame per beat with the product in it, lay each on the timeline for that beat's length, voice each beat lined up with its start (your cloned voice if you have one, otherwise a free Edge voice), add the on-screen lines, and export a vertical short. Nobody appears on camera. Only the selling points you provide are used — no invented claims or figures.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(REFERENCE_IMAGE_MODEL, zh="能带参考图出图的图像模型", en="Image model that takes reference images"),
            requirement(
                CLONED_VOICE, zh="嗓子可选:配音库的克隆音色(没有就用免费的 Edge 音色)",
                en="Optional voice: a cloned voice from the voice library (otherwise a free Edge voice)", optional=True,
            ),
            requirement(None, zh="一张商品图", en="A product photo"),
        ],
        "stages": {
            "zh": ["填商品名与卖点(一行一条,只写你能负责的)", "写分拍口播脚本", "逐拍出画面、配画外音并铺上时间线", "按每拍的落点铺屏幕短句", "导出竖屏成片"],
            "en": ["Product name and selling points (one per line, only claims you can stand behind)", "Write the beat-by-beat script",
                   "Paint and voice each beat onto the timeline", "Lay each beat's on-screen line", "Export the vertical short"],
        },
    },
    {
        "id": FOOTAGE_MONTAGE,
        "name": {"zh": "自有素材混剪 · 配音与字幕", "en": "Montage from your own footage"},
        "summary": {
            "zh": "按标签取出你已经拍好的一批素材,让模型排出叙事顺序、定每段用哪条素材的哪一截、写好旁白,然后按顺序接上时间线,逐段配音(有旁白的那段把原声压低)并铺字幕,导出成片。不生成任何画面 —— 画面就是你自己的素材;没有配音音色时自动只出字幕。标签没填或这个标签下没有视频时,停下并告诉你。一次最多取这个标签下的 200 条视频,更多的先按更细的标签分批。",
            "en": "Pull a tagged batch of footage you already shot, let the model order the story, decide which part of which clip each beat uses, and write the narration; then lay every segment on the timeline in order, speak and caption each one (ducking the footage's own sound under the narration), and export. Nothing is generated — the picture is your own footage, and without a configured voice it falls back to captions only. If the tag is blank or has no videos, it stops and tells you. Up to 200 videos under the tag are used at a time; split larger batches with finer tags first.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(None, zh="一批打了同一个标签的视频素材", en="A batch of video assets sharing one tag"),
            requirement(
                CLONED_VOICE, zh="旁白可选:配音库的克隆音色", en="Optional narration: a cloned voice", optional=True,
            ),
        ],
        "stages": {
            "zh": ["填主题与素材标签(先给要混剪的视频打上同一个标签)", "按标签取出素材", "排出叙事顺序与旁白", "按顺序接上时间线", "逐段配音并铺字幕", "导出成片"],
            "en": ["Topic and footage tag (tag the videos to cut with one shared tag first)", "Fetch the footage by tag",
                   "Order the story and write the narration", "Lay the segments in order", "Speak and caption each one", "Export"],
        },
    },
    {
        "id": FABRIC_LOOKBOOK,
        "name": {"zh": "面料 → 应用效果图与规格页", "en": "Fabric into applications and a spec sheet"},
        "summary": {
            "zh": "给一块面料的实拍图和参数,规划它真正适合做的几种成品(最多 12 种),每种出一张放在真实空间里的效果图,并生成一页可直接发客户的规格与应用提案。规格只复述你给出的参数,没给的写「需与工厂确认」。每一种是一次付费出图。",
            "en": "From one fabric photo and its specs, plan the products it genuinely suits (up to 12), render each one in a real space, and produce a one-page proposal you can send to a client. The spec sheet only restates the numbers you provide; anything missing is marked as needing mill confirmation. Each application is one paid image generation.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(REFERENCE_IMAGE_MODEL, zh="能带参考图出图的图像模型", en="Image model that takes reference images"),
            requirement(None, zh="一张面料实拍图", en="A photo of the actual fabric"),
        ],
        "stages": {
            "zh": ["填面料参数(名称、成分、克重、幅宽、手感;没有的留空)", "选择面料图", "规划应用与规格卡", "逐种出成品效果图", "生成可发客户的规格页"],
            "en": ["Fabric specs (name, composition, weight, width, hand feel; leave unknowns blank)", "Pick the fabric photo",
                   "Plan applications and the spec sheet", "Render each application", "Write the spec sheet to send"],
        },
    },
    {
        "id": TALKING_SCRIPT_VIDEO,
        "name": {"zh": "稿子 → 数字人口播", "en": "Script into a talking-head video"},
        "summary": {
            "zh": "一张正脸加一段稿子:逐句配音,按说话照片模型一次能收的长度分段,每段让这张脸说出来,首尾相接铺上时间线,字幕按配音的实际时长铺好,导出成片。成片带「AI 生成」标识。运行前在「让它说话」上确认已取得授权。",
            "en": "A portrait and a script: voice it sentence by sentence, group the sentences into segments the speaking-photo model accepts, make the face speak each one, lay them end to end on the timeline, caption from the real voicing times, and export. The export carries an \"AI-generated\" label. Confirm consent on \"Make it speak\" before running.",
        },
        "requires": [
            requirement(SPEECH_VIDEO_MODEL, zh="会「说话照片」的视频模型", en="A speaking-photo video model"),
            requirement(DIGITAL_HUMAN_VOICE, zh="一把嗓子:配音库的克隆音色(要声明是谁的)",
                        en="A voice: a cloned voice with a consent declaration"),
            requirement(None, zh="一张清晰的单人正脸", en="A clear, single-person portrait"),
        ],
        "stages": {
            "zh": ["选一张正脸", "在「长稿分段配音」里贴稿子、挑音色", "长稿分段配音", "逐段让它说话并接上时间线", "按配音时间铺字幕", "导出成片"],
            "en": ["Pick a portrait", "Paste the script and pick the voice on “Voice the script in segments”", "Voice the script in segments",
                   "Make each segment speak onto the timeline", "Caption from the voicing times", "Export the video"],
        },
    },
    {
        "id": PRODUCT_PITCH_PRESENTER,
        "name": {"zh": "商品 → 数字人出镜带货口播", "en": "Product into a presenter-led short"},
        "summary": {
            "zh": "在「带货口播短视频」的基础上,开场钩子和收尾号召换成资产库里的一位人物出镜说出来(用它的脸和嗓子),中间每一拍仍是带商品的画面,口播用同一个嗓子念、对齐每一拍的开头,每拍铺上屏幕短句,导出竖屏成片(带「AI 生成」标识)。运行前在「挑一位主播」上选好人物;人物要先在资产库里有正面图和音色;真人要有授权声明,克隆音色也要声明是谁的。",
            "en": "Everything in the narrated short, but a character from your asset library speaks the hook and the call to action on camera (with its own face and voice), while each beat in between stays a product shot voiced in the same voice, lined up with the beat and captioned, exported as a vertical short with an \"AI-generated\" label. Pick the character on “Pick the presenter” before running; it needs a front image and a voice in the asset library; real people need a consent declaration, and a cloned voice needs one too.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            requirement(REFERENCE_IMAGE_MODEL, zh="能带参考图出图的图像模型", en="Image model that takes reference images"),
            requirement(SPEECH_VIDEO_MODEL, zh="会「说话照片」的视频模型", en="A speaking-photo video model"),
            requirement(None, zh="资产库里一位有正面图和音色的人物", en="A character in the asset library with a front image and a voice"),
            requirement(None, zh="一张商品图", en="A product photo"),
        ],
        "stages": {
            "zh": ["填商品名与卖点(一行一条,只写你能负责的)", "挑一位主播", "写分拍口播脚本", "主播出镜说开场", "逐拍出画面、配画外音", "主播出镜说收尾", "导出竖屏成片"],
            "en": ["Product name and selling points (one per line, only claims you can stand behind)", "Pick the presenter",
                   "Write the beat-by-beat script", "Presenter speaks the hook",
                   "Paint and voice each beat", "Presenter speaks the call to action", "Export the vertical short"],
        },
    },
]


# --------------------------------------------------------------------------------------
# 5 · 自有素材混剪(企业宣传 / 产线介绍 / 展会回顾)
# --------------------------------------------------------------------------------------


def _montage_schema() -> dict[str, Any]:
    caption = _object(
        {
            # 和切片模板同一条:**相对这一段自己的开头**。这一段落在成片第几秒是运行时才知道的
            # (由 timeline_append 回报),所以模型不需要、也不该去算累计时间。
            "start": {"type": "number", "minimum": 0, "description": "相对本段开头的秒数"},
            "end": {"type": "number", "minimum": 0},
            "text": _str("这一句字幕,短句"),
        },
        ["start", "end", "text"],
    )
    segment = _object(
        {
            "segment_title": _str("这一段在讲什么,中文,给人看的"),
            "asset_id": _str("用素材清单里的哪一条,**原样抄它的 id**,不要改写、不要编"),
            "source_name": _str("那条素材的名字,抄一遍,方便人核对选得对不对"),
            "src_start": {"type": "number", "minimum": 0, "description": "从这条素材的第几秒开始取"},
            #: **给终点,不给"取多长"。** 此前只有 src_start + seconds,而「接到时间线」没有终点就取到素材末尾 ——
            #: 每一段都是从起点一直到那条素材结束,然后被加速塞进 seconds(最多 1.5 倍,再长就超出去)。
            "src_end": {"type": "number", "minimum": 0, "description": "取到这条素材的第几秒为止;不能超过它的时长"},
            "seconds": {
                "type": "number", "minimum": 1.5, "maximum": 20,
                "description": "这一段在成片里多长,必须等于 src_end − src_start;旁白按它压",
            },
            "narration": _str("这一段的口播原文,中文;念出来不超过本段时长,没有旁白就写空字符串"),
            "captions": {"type": "array", "items": caption, "minItems": 1},
            "why": _str("为什么这一段放在这个位置"),
        },
        ["segment_title", "asset_id", "source_name", "src_start", "src_end", "seconds", "narration", "captions", "why"],
    )
    return _object(
        {
            "storyline": _str("整条片子的叙事线,一两句话"),
            "segments": {"type": "array", "items": segment, "minItems": 2, "maxItems": 24},
            "unused_note": _str("哪些素材没用上、为什么;全用上了写空字符串"),
        },
        ["storyline", "segments", "unused_note"],
    )


#: 混剪一次最多从这个标签下取几条视频交给模型排。
MONTAGE_FOOTAGE_LIMIT = 200

#: 有旁白的那一段,素材自带的原声压到多少(线性增益,1 = 原样)。不静音:现场声压低了垫在旁白底下,
#: 比一段死寂的画面自然;但也不能和旁白一样响,否则两个声音打架,旁白听不清。
DUCKED_SOURCE_GAIN = 0.2


def footage_montage_graph(*, chat: Any, voice_id: str = "") -> dict[str, Any]:
    """一批自有素材 → 规划叙事顺序 → 按顺序接上时间线 → 逐段配音与字幕 → 导出。

    **这是企业最常见、而此前一个模板都没覆盖的形态。** 工厂有车间、产线、检测、发货的零散素材;
    服装厂有面料特写、生产线、成衣、质检;展会结束有一堆现场片段。他们要的不是生成画面 ——
    画面早就拍好了,缺的是"先讲什么、后讲什么、每段留多久、配什么话"。

    和别的模板的三处不同:

    - **起点是一批素材,不是一条。** 用 `asset_query` 按标签批量取,这是所有模板里第一个这么做的。
      素材清单(名字 + 时长)交给模型去排顺序,而不是让用户自己拖时间线。**标签是必填的开始参数**(空着取到的
      是整个素材库);这个标签下一条视频都没有,就停在这里并说清楚,而不是让模型对着空清单编 id。
    - **不生成任何画面。** 和「长视频切多条竖屏」一样,除了配音没有生成开销。
    - **口播按段对齐,不是一条音轨铺到底。** 每一段的旁白单独合成,落在**这一段自己的起点**上
      —— 起点由 `timeline_append` 运行时回报(`timeline_start`),所以不管前面几段实际多长,
      音画都不会越走越偏。字幕同理,用同一个起点做偏移。有旁白的那一段,素材原声压低垫在底下。

    没有配音音色时整条仍然可用:旁白那几步被条件挡掉,字幕照出 —— 很多企业片本来就是纯字幕。
    """
    system = """你是企业宣传片的编导。用户会给你一批**已经拍好**的素材(每条有名字和时长)和一个主题，
你要把它们排成一条讲得通的片子。

硬性要求：
- asset_id 必须**原样抄自素材清单**。不要改写、不要缩短、更不要编一个出来——抄错这一段就是空的。
- 每一段从这条素材的 src_start 取到 src_end：src_end 不能超过那条素材的时长；seconds 就是 src_end − src_start。
- 顺序要有叙事:开头给出观看理由,中段按因果或流程推进,结尾落到一个明确的信息或行动。
  不要按素材的文件名顺序排。
- narration 念出来不能超过这一段的 seconds:中文按每秒约 4 个字估，宁短勿长；
  这一段不需要旁白就写空字符串。
- captions 的时间码**相对这一段自己的开头**，不是成片时间。
- 只描述素材里真的有的东西。不要编造产能、资质、检测结论、客户名称或任何数字——
  没有依据的话一句都不要写。
- 素材不够讲完这个主题时，宁可做短一点，并在 unused_note 里说明缺什么。

只输出符合 JSON Schema 的对象。"""

    body_nodes: list[dict[str, Any]] = [
        {
            "id": "place_shot",
            "type": "timeline_append",
            "name": {"zh": "把这一段接上去", "en": "Append this segment"},
            "position": {"x": 80, "y": 140},
            "config": {
                "sequence_id": "{{input.sequence_id}}",
                "asset_id": "{{loop.item.asset_id}}",
                "track_id": "{{input.video_track_id}}",
                "start": "{{loop.item.src_start}}",
                "end": "{{loop.item.src_end}}",
            },
        },
        {
            "id": "has_voice",
            "type": "condition",
            "name": {"zh": "配了音色吗", "en": "Is a voice configured?"},
            "position": {"x": 400, "y": 300},
            "config": {"left": "{{input.voice_id}}", "op": "not_empty"},
        },
        {
            "id": "has_narration",
            "type": "condition",
            "name": {"zh": "这一段有旁白吗", "en": "Does this segment have narration?"},
            "position": {"x": 720, "y": 300},
            "config": {"left": "{{loop.item.narration}}", "op": "not_empty"},
        },
        {
            "id": "narrate",
            "type": "synthesize_speech",
            "name": {"zh": "念这一段的旁白", "en": "Speak this segment's narration"},
            "position": {"x": 1040, "y": 300},
            "config": {"text": "{{loop.item.narration}}", "engine": "builtin:clone", "voice": "{{input.voice_id}}"},
        },
        {
            "id": "place_voice",
            "type": "timeline_append",
            "name": {"zh": "把旁白对齐到这一段的起点", "en": "Align the narration to this segment's start"},
            "position": {"x": 1360, "y": 300},
            "config": {
                "sequence_id": "{{input.sequence_id}}",
                "asset_id": "{{narrate.asset_id}}",
                "track_id": "{{input.audio_track_id}}",
                # **起点由上面那一步运行时回报**,不是算出来的。前面几段实际多长不重要,
                # 音画都落在同一个数上,不会越走越偏。
                "at": "{{place_shot.timeline_start}}",
                #: 最长就是这一段画面**实际**占的秒数(素材比计划短时出点被夹到素材末尾,比 seconds 短)。
                #: 念得比它长就加速塞进去(最多 1.5 倍);还放不下就裁掉尾巴 —— 不压到下一段,成片尾也不留黑。
                "max_duration": "{{place_shot.duration}}",
                "trim_overflow": "yes",
            },
        },
        {
            "id": "voice_overflow",
            "type": "condition",
            "name": {"zh": "旁白裁掉了尾巴吗", "en": "Was the narration cut short?"},
            "position": {"x": 1680, "y": 480},
            "config": {"left": "{{place_voice.trimmed}}", "op": "gt", "right": "0"},
        },
        {
            "id": "overflow_notice",
            "type": "notify",
            "name": {"zh": "说一声旁白被裁了", "en": "Say the narration was cut"},
            "position": {"x": 2000, "y": 480},
            "config": {
                "title": "混剪:有一段旁白念不完",
                "body": "「{{loop.item.segment_title}}」这一段的旁白加速到 1.5 倍仍比画面长 {{place_voice.trimmed}} 秒,"
                        "超出的部分已裁掉。想保住整句,把这一段的旁白改短,或把这一段的素材取长一点再运行一次。",
            },
        },
        {
            "id": "duck_source",
            "type": "edit_timeline",
            "name": {"zh": "旁白底下压低原声", "en": "Duck the footage's own sound under the narration"},
            "position": {"x": 1680, "y": 300},
            "config": {
                "sequence_id": "{{input.sequence_id}}",
                #: 基底视频轨的原声默认是混进成片的;不压的话现场声和旁白一样响,旁白听不清。
                "operations": (
                    '[{"kind": "set_clip_gain", "clip_id": "{{place_shot.clip_id}}", '
                    f'"gain": {DUCKED_SOURCE_GAIN}, "muted": false}}]'
                ),
            },
        },
        {
            "id": "caption_shot",
            "type": "generate_subtitles",
            "name": {"zh": "铺这一段的字幕", "en": "Lay this segment's captions"},
            "position": {"x": 400, "y": 60},
            "config": {
                "sequence_id": "{{input.sequence_id}}",
                "segments": "{{loop.item.captions}}",
                # 同一个起点。字幕轨第一段建出来,后面几段自动落到同一条上(见 _subtitle_track)。
                "offset": "{{place_shot.timeline_start}}",
                #: 裁到这一段**实际**的终点:素材比计划短时,模型按计划写的字幕不盖到下一段上。
                "until": "{{place_shot.timeline_end}}",
                "allow_empty": "yes",
            },
        },
    ]
    body_edges = [
        {"id": "shot_caption", "source": "place_shot", "target": "caption_shot"},
        #: 旁白那一串排在字幕**之后**,不和它同时跑:两边改的是同一条时间线,同时提交时后到的那个撞上版本号
        #: (「这个序列刚被改过」),整条混剪失败。字幕不挂在条件后面,有没有旁白都照出。
        {"id": "caption_voice", "source": "caption_shot", "target": "has_voice"},
        {"id": "voice_narration", "source": "has_voice", "target": "has_narration", "source_handle": "true"},
        {"id": "narration_speak", "source": "has_narration", "target": "narrate", "source_handle": "true"},
        {"id": "speak_place", "source": "narrate", "target": "place_voice"},
        #: **这一条不能省。** 「念旁白 → 放旁白」同一对节点间还有一条数据边(asset_id),规范化时无 handle 的控制边
        #: 会被折进数据边;而只剩数据边时,任一上游跑过就算激活 —— 「接上这一段」总是跑过的,于是这一段没有旁白
        #: (或者根本没配音色)时「放旁白」拿着空素材照跑,整条混剪失败。带 handle 的边有路由语义,不会被折掉。
        {"id": "narration_place", "source": "has_narration", "target": "place_voice", "source_handle": "true"},
        {"id": "place_duck", "source": "place_voice", "target": "duck_source"},
        {"id": "place_overflow", "source": "place_voice", "target": "voice_overflow"},
        {"id": "overflow_notify", "source": "voice_overflow", "target": "overflow_notice", "source_handle": "true"},
    ]

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填主题与素材标签", "en": "Topic and footage tag"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    #: 这两格留空,不放说明文字:此前 footage_tag 写着「给要混剪的素材打上同一个标签,把它写在这里」,
                    #: 没改就跑的话按这句话去查标签,一条都取不到,模型对着空清单编了 id。要填什么写在模板卡片上;
                    #: 空着运行前就拦(required_params)。
                    "topic": "",
                    "footage_tag": "",
                    "audience": "潜在客户与合作方",
                    "tone": "专业、克制、可信",
                    "target_duration_seconds": 60,
                    "voice_id": voice_id,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                },
                #: 标签空着的话「按标签取」取到的是整个素材库 —— 那不是用户要混剪的那一批,所以运行前就拦。
                "required_params": ["topic", "footage_tag"],
            },
        },
        {
            "id": "footage",
            "type": "asset_query",
            "name": {"zh": "按标签取出这批素材", "en": "Fetch the footage by tag"},
            "position": {"x": 330, "y": 260},
            #: 一次最多取 200 条(模板卡片上写明了)。此前是 60 条:一个展会、一条产线的素材常常不止这些,多出来的
            #: 悄悄不进清单,模型也就不知道它们存在。再多就该先按更细的标签分批。
            "config": {"kind": "video", "tags": "{{start.footage_tag}}", "limit": MONTAGE_FOOTAGE_LIMIT},
        },
        {
            "id": "has_footage",
            "type": "condition",
            "name": {"zh": "取到素材了吗", "en": "Was any footage found?"},
            "position": {"x": 650, "y": 260},
            #: 按条数判(数值比较),不按清单空不空判。
            "config": {"left": "{{footage.count}}", "op": "gt", "right": "0"},
        },
        {
            "id": "no_footage_notice",
            "type": "notify",
            "name": {"zh": "没有可混剪的素材", "en": "No footage to cut"},
            "position": {"x": 1290, "y": 520},
            "config": {
                "title": "混剪没有开始:没取到素材",
                "body": "标签「{{start.footage_tag}}」下没有视频素材。给要混剪的视频打上同一个标签,"
                        "把这个标签填进开始节点的 footage_tag,再运行一次。",
            },
        },
        {
            "id": "montage_plan",
            "type": "llm",
            "name": {"zh": "排出叙事顺序与旁白", "en": "Order the story and write the narration"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "precise",
                "system": system,
                "prompt": """这条片子要讲的事：{{start.topic}}
目标观众：{{start.audience}}
语气：{{start.tone}}
成片目标时长：{{start.target_duration_seconds}} 秒

可用素材清单（共 {{footage.count}} 条，含 id、名字与时长）：
{{footage.assets}}

请把它们排成一条讲得通的片子。再强调一次：asset_id 必须原样抄清单里的 id；
captions 的时间码相对每一段自己的开头。""",
                "response_format": "json_schema",
                "json_schema_name": "footage_montage_plan",
                "json_schema": _montage_schema(),
                "json_schema_strict": "true",
                "temperature": 0.4,
                "max_tokens": 16000,
            },
        },
        {
            "id": "montage_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立成片时间线", "en": "Create the timeline"},
            "position": {"x": 1290, "y": 460},
            "config": {
                "name": "{{start.topic}} · 混剪",
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "lay_segments",
            "type": "loop_foreach",
            "name": {"zh": "按顺序接上时间线并配音配字幕", "en": "Lay every segment, with narration and captions"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "items": "{{montage_plan.json.segments}}",
                "inputs": {
                    "sequence_id": "{{montage_project.sequence_id}}",
                    "video_track_id": "{{montage_project.video_track_id}}",
                    "audio_track_id": "{{montage_project.audio_track_id}}",
                    "voice_id": "{{start.voice_id}}",
                },
                "body": {"nodes": body_nodes, "edges": body_edges},
                # **顺序就是叙事**,并发的落位顺序是谁先回来谁在前。
                "concurrency": 1,
                "output": "{{place_shot.clip_id}}",
            },
        },
        {
            "id": "export_montage",
            "type": "export_sequence",
            "name": {"zh": "导出混剪成片", "en": "Export the montage"},
            "position": {"x": 1930, "y": 260},
            "config": {"sequence_id": "{{montage_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "混剪完成通知", "en": "Montage ready"},
            "position": {"x": 2250, "y": 260},
            "config": {
                "title": "混剪成片已导出",
                "body": "{{start.topic}} 已用 {{lay_segments.count}} 段素材完成混剪。",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付成片与剪辑方案", "en": "Hand over the cut and the plan"},
            "position": {"x": 2570, "y": 260},
            "config": {
                "values": {
                    "final_asset_id": "{{export_montage.asset_id}}",
                    "sequence_id": "{{montage_project.sequence_id}}",
                    "plan": "{{montage_plan.json}}",
                    "storyline": "{{montage_plan.json.storyline}}",
                    "unused_note": "{{montage_plan.json.unused_note}}",
                    "segment_clip_ids": "{{lay_segments.results}}",
                    "footage_count": "{{footage.count}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_footage", "source": "start", "target": "footage"},
        {"id": "footage_check", "source": "footage", "target": "has_footage"},
        #: 这个标签下一条视频都没有,就停在这里说清楚 —— 之后的对话(计费)和建项目都不跑,模型也不会对着空清单编 id。
        {"id": "no_footage", "source": "has_footage", "target": "no_footage_notice", "source_handle": "false"},
        {"id": "footage_plan", "source": "has_footage", "target": "montage_plan", "source_handle": "true"},
        #: 时间线在排好叙事之后才建:此前和那次对话并行,对话失败时留下一个空项目。
        {"id": "plan_project", "source": "montage_plan", "target": "montage_project"},
        {"id": "plan_lay", "source": "montage_plan", "target": "lay_segments"},
        {"id": "project_lay", "source": "montage_project", "target": "lay_segments"},
        {"id": "lay_export", "source": "lay_segments", "target": "export_montage"},
        {"id": "export_notice", "source": "export_montage", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": FOOTAGE_MONTAGE, "template_version": 3, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )
