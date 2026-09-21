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

from app.ai.providers import FIRST_FRAME, REFERENCE_IMAGE
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph

HIGHLIGHT_SHORTS = "highlight_shorts"
PRODUCT_ON_MODEL = "product_on_model"
PRODUCT_PITCH_SHORT = "product_pitch_short"
FABRIC_LOOKBOOK = "fabric_lookbook"

#: 竖屏。短视频平台的默认画幅 —— 横屏素材按 cover 居中裁进来(和剪辑台的「改画幅」同一套)。
VERTICAL = {"width": 1080, "height": 1920}

#: 生成类模板一次最多做多少组。**不是性能上限,是钱的上限**:每一组都是一次付费生成,而跑之前
#: 用户看不到账单。给一个明确的上限,比事后解释为什么扣了这么多好。
MAX_VARIANTS = 12


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
            "clips": {"type": "array", "items": clip, "minItems": 1},
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
    - **每条切片自己一条序列。** 不是在一条时间线上切十刀 —— 那样十条片子共用一个导出,拿不到
      十个文件。循环体里各建各的,导出也各是各的。
    """
    system = """你是短视频运营和剪辑师。你会收到一条长视频(口播、访谈或直播回放)的带时间码逐字稿，
任务是从里面挑出能**独立成立**的片段：不依赖前文也听得懂、有一个完整的观点或故事、开头三秒就有
抓人的理由。

硬性要求：
- 每条片段的时长必须在给定的上下限之间；片段之间不得重叠；起止时间必须落在素材时长内。
- 起止时间要卡在**句子边界**上，不要从半句话开始或结束。
- 只挑真的够格的。素材里没有那么多高光时，宁可少给几条，并在 skipped_reason 里说明——
  凑数的片段发出去是在消耗账号。
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
            "config": {"asset_id": "{{source_video.asset_id}}", "engine": "auto"},
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
            "id": "cut_clips",
            "type": "loop_foreach",
            "name": {"zh": "逐条切成竖屏成片", "en": "Cut each one into a vertical export"},
            "position": {"x": 1290, "y": 260},
            "config": {
                "items": "{{highlights.json.clips}}",
                "inputs": {
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
            },
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "切片完成通知", "en": "Clips ready"},
            "position": {"x": 1610, "y": 260},
            "config": {
                "title": "竖屏切片已导出",
                "body": "{{source_video.name}} 已切出 {{cut_clips.count}} 条竖屏成片,均带字幕。",
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
        {"id": "highlights_cut", "source": "highlights", "target": "cut_clips"},
        {"id": "cut_notice", "source": "cut_clips", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": HIGHLIGHT_SHORTS, "template_version": 1, "source": "official"},
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
    "sleeves, extra logos, text, watermark, deformed hands, extra limbs"
)


def _lookbook_schema(*, wants_video: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "scene_label": _str("这组图的场合名,给人看的,如「通勤 · 清晨街头」"),
        "model_brief": _str("模特设定,英文:年龄段、体型、发型、妆容、神态"),
        "setting": _str("场景与光线,英文"),
        "pose": _str("姿态与取景,英文;要能看清商品的版型"),
        "image_prompt": _str("完整出图提示词,英文,不含机位参数"),
    }
    required = ["scene_label", "model_brief", "setting", "pose", "image_prompt"]
    if wants_video:
        properties["video_prompt"] = _str("这组的 5 秒视频提示词,英文:模特的动作节拍与轻微运镜")
        required.append("video_prompt")
    scene = _object(properties, required)
    return _object(
        {
            "product_summary": _str("用一句话复述这件商品的可见特征,证明你看懂了参数"),
            "scenes": {"type": "array", "items": scene, "minItems": 1},
            "copy_lines": {
                "type": "array",
                "items": _str(),
                "minItems": 1,
                "description": "可直接用的中文卖点短句,每条不超过 20 字",
            },
        },
        ["product_summary", "scenes", "copy_lines"],
    )


def product_on_model_graph(*, chat: Any, image: Any, video: Any) -> dict[str, Any]:
    """一张商品图(平铺图 / 面料图)→ 规划 N 组场景 → 每组出一张模特上身图 →(可选)出一段短视频。

    **商品图贯穿每一次生成**,不是只喂第一次:每一组场景的出图都把它作为 `reference_image` 带上,
    视频那一步再把刚生成的上身图作为 `first_frame` 带上。这样"这件衣服"在整条链路上只有一个来源。

    不让模型"看"商品图去写文案 —— `llm` 节点发不出图片。商品的品类、颜色、材质由用户在参数里写一句,
    模型据此规划场景;像不像由参考图保证,不是由描述保证。
    """
    wants_video = bool(getattr(video, "model", ""))

    system = """你是服装 / 面料品牌的视觉企划和电商内容负责人。用户会给你一件商品的基本信息和目标人群，
你要规划几组**能直接投放**的模特上身场景。

硬性要求：
- 每一组是一个真实存在的穿着场合，彼此要拉开差别（场合、光线、季节感、构图各不相同），
  不要只换背景色。
- image_prompt 用英文完整描述画面：模特、姿态、取景、环境、光线、氛围。**不要写机位参数**，
  也不要在画面里生成文字、logo 水印或 UI。
- 你**看不到**那张商品图，所以不要描述商品本身的细节——那由参考图保证。你只描述"穿着它的人
  在什么场合、怎么站、光怎么打"。提到商品时用 the product / the garment 指代。
- copy_lines 是中文卖点短句，可以直接配在图上或发在详情页，不要写成广告腔的空话。

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
                    "Photorealistic commercial fashion photography, no text, no watermark."
                ),
                "negative_prompt": _NEGATIVE_PRODUCT,
                "parameters": {},
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
    loop_output = "{{on_model.asset_id}}"

    if wants_video:
        body_nodes.append(
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
                    "parameters": {"duration_seconds": 5},
                    # 首帧就是刚出的那张上身图 —— 视频和静图因此必然是同一套衣服、同一个人。
                    "source_assets": [
                        f"{{{{on_model.asset_id}}}}:{FIRST_FRAME}",
                        f"{{{{input.product_asset_id}}}}:{REFERENCE_IMAGE}",
                    ],
                },
            }
        )
        body_edges.append({"id": "file_clip", "source": "file_image", "target": "on_model_clip"})
        loop_output = "{{on_model_clip.asset_id}}"

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "描述商品与人群", "en": "Describe the product and the audience"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "product_name": "",
                    "product_brief": "品类、颜色、材质、版型,一两句话",
                    "audience": "25-35 岁都市通勤女性",
                    "season": "春秋",
                    "brand_tone": "简洁、克制、质感",
                    "scene_count": 4,
                }
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
            "id": "shoot_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立这次拍摄的项目", "en": "Create a project for this shoot"},
            "position": {"x": 650, "y": 420},
            "config": {
                "name": "{{start.product_name}} · 上身图",
                "width": VERTICAL["width"],
                "height": VERTICAL["height"],
                "fps": 30,
            },
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
                "json_schema": _lookbook_schema(wants_video=wants_video),
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
                "inputs": {
                    "product_asset_id": "{{product_photo.asset_id}}",
                    "product_name": "{{start.product_name}}",
                    "project_id": "{{shoot_project.project_id}}",
                },
                "body": {"nodes": body_nodes, "edges": body_edges},
                "output": loop_output,
                "concurrency": 2,
            },
        },
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

{{lookbook_plan.json.copy_lines}}

## 拍摄场景

{{lookbook_plan.json.scenes}}
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
                "body": "{{start.product_name}} 已出 {{shoot_scenes.count}} 组,卖点文案已存进笔记。",
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
                    "generated_asset_ids": "{{shoot_scenes.results}}",
                    "scene_count": "{{shoot_scenes.count}}",
                    "plan": "{{lookbook_plan.json}}",
                    "copy_note_id": "{{copy_note.note_id}}",
                    "project_id": "{{shoot_project.project_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_photo", "source": "start", "target": "product_photo"},
        {"id": "start_plan", "source": "start", "target": "lookbook_plan"},
        {"id": "photo_project", "source": "product_photo", "target": "shoot_project"},
        {"id": "plan_shoot", "source": "lookbook_plan", "target": "shoot_scenes"},
        {"id": "photo_shoot", "source": "product_photo", "target": "shoot_scenes"},
        {"id": "project_shoot", "source": "shoot_project", "target": "shoot_scenes"},
        {"id": "plan_note", "source": "lookbook_plan", "target": "copy_note"},
        {"id": "shoot_notice", "source": "shoot_scenes", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
        {"id": "note_output", "source": "copy_note", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": PRODUCT_ON_MODEL, "template_version": 1, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


# --------------------------------------------------------------------------------------
# 3 · 商品 → 带货口播短视频
# --------------------------------------------------------------------------------------


def _pitch_schema() -> dict[str, Any]:
    beat = _object(
        {
            "narration": _str("这一拍要念的口播原文,中文;念出来不超过本拍时长"),
            "seconds": {"type": "number", "minimum": 2, "maximum": 8, "description": "这一拍多长"},
            "visual_prompt": _str("这一拍的画面,英文;商品必须在画面里"),
            "caption": _str("屏幕上的短句,不超过 14 字"),
        },
        ["narration", "seconds", "visual_prompt", "caption"],
    )
    return _object(
        {
            "hook_line": _str("前三秒的钩子,中文"),
            "beats": {"type": "array", "items": beat, "minItems": 2},
            "call_to_action": _str("结尾行动号召,中文"),
        },
        ["hook_line", "beats", "call_to_action"],
    )


def product_pitch_short_graph(*, chat: Any, image: Any, voice_id: str = "") -> dict[str, Any]:
    """商品图 + 几条卖点 → 口播脚本(分拍)→ 每拍出一张画面 + 配一段音 → 组装 → 字幕 → 导出。

    和「模特上身图」的分别:那个交付的是**素材**(图和视频,你拿去自己用),这个交付的是**一条成片**。

    口播和画面按"拍"对齐:每一拍自己的时长由脚本给出,画面按这个时长铺在时间线上,配音也按拍合成。
    这样画面切换和话说到哪儿是对得上的 —— 而不是先出一段音再让画面自己猜。
    """
    system = """你是带货短视频的编导。用户给你一件商品和几条卖点，你要写一条 20-45 秒、能直接拍的
口播脚本，按"拍"拆开。

硬性要求：
- 前三秒必须给出观看理由，不要从"大家好"开始。
- 每一拍的 narration 念出来不能超过这一拍的 seconds：中文按每秒约 4 个字估，宁短勿长。
- visual_prompt 用英文写这一拍的画面，**商品必须出现在画面里**；不要写机位参数，不要在画面里
  生成文字、logo 或水印。
- 卖点只能来自用户给的那几条，不要编造功效、成分、资质或数据。
- caption 是屏幕上的短句，不是把 narration 原样抄一遍。

只输出符合 JSON Schema 的对象。"""

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填商品与卖点", "en": "Product and selling points"},
            "position": {"x": 40, "y": 260},
            "config": {
                "params": {
                    "product_name": "",
                    "selling_points": "一行一条,只写你能负责的卖点",
                    "audience": "刷竖屏短视频的年轻观众",
                    "target_duration_seconds": 30,
                    "voice_id": voice_id,
                    "width": VERTICAL["width"],
                    "height": VERTICAL["height"],
                    "fps": 30,
                }
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
                "prompt": """商品名称：{{start.product_name}}
卖点（只能用这些）：
{{start.selling_points}}
目标观众：{{start.audience}}
成片目标时长：{{start.target_duration_seconds}} 秒

请写出分拍脚本。各拍 seconds 之和要接近目标时长。""",
                "response_format": "json_schema",
                "json_schema_name": "product_pitch_script",
                "json_schema": _pitch_schema(),
                "json_schema_strict": "true",
                "temperature": 0.6,
                "max_tokens": 6000,
            },
        },
        {
            "id": "pitch_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立竖屏成片时间线", "en": "Create the vertical timeline"},
            "position": {"x": 650, "y": 420},
            "config": {
                "name": "{{start.product_name}} · 带货短片",
                "width": "{{start.width}}",
                "height": "{{start.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "shoot_beats",
            "type": "loop_foreach",
            "name": {"zh": "逐拍出画面并上时间线", "en": "Shoot each beat onto the timeline"},
            "position": {"x": 970, "y": 260},
            "config": {
                "items": "{{pitch_script.json.beats}}",
                "inputs": {
                    "product_asset_id": "{{product_photo.asset_id}}",
                    "sequence_id": "{{pitch_project.sequence_id}}",
                    "video_track_id": "{{pitch_project.video_track_id}}",
                    "project_id": "{{pitch_project.project_id}}",
                },
                "body": {
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
                                    "Vertical composition for a phone screen, photorealistic, "
                                    "no text, no logo overlay, no watermark."
                                ),
                                "negative_prompt": _NEGATIVE_PRODUCT,
                                "parameters": {},
                                "source_assets": [f"{{{{input.product_asset_id}}}}:{REFERENCE_IMAGE}"],
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
                                "max_duration": "{{loop.item.seconds}}",
                            },
                        },
                    ],
                    "edges": [{"id": "frame_place", "source": "beat_frame", "target": "beat_on_timeline"}],
                },
                # 画面要按拍的顺序首尾相接,所以**不能并发** —— 并发的落位顺序是谁先回来谁在前。
                "concurrency": 1,
                "output": "{{beat_on_timeline.clip_id}}",
            },
        },
        {
            "id": "voice_over",
            "type": "synthesize_speech",
            "name": {"zh": "合成整条口播", "en": "Synthesize the voice-over"},
            "position": {"x": 970, "y": 480},
            "config": {
                "text": "{{pitch_script.json.hook_line}}\n{{pitch_script.json.call_to_action}}",
                "engine": "clone",
                "voice": "{{start.voice_id}}",
            },
        },
        {
            "id": "voice_on_timeline",
            "type": "timeline_append",
            "name": {"zh": "把口播放到音频轨", "en": "Put the voice-over on the audio track"},
            "position": {"x": 1290, "y": 480},
            "config": {
                "sequence_id": "{{pitch_project.sequence_id}}",
                "asset_id": "{{voice_over.asset_id}}",
                "track_id": "{{pitch_project.audio_track_id}}",
                "at": 0,
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
                "title": "带货短片已导出",
                "body": "{{start.product_name}} 的口播短片已完成,共 {{shoot_beats.count}} 拍。",
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
                    "beat_clip_ids": "{{shoot_beats.results}}",
                    "voice_asset_id": "{{voice_over.asset_id}}",
                    "sequence_id": "{{pitch_project.sequence_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_photo", "source": "start", "target": "product_photo"},
        {"id": "start_script", "source": "start", "target": "pitch_script"},
        {"id": "start_project", "source": "start", "target": "pitch_project"},
        {"id": "script_shoot", "source": "pitch_script", "target": "shoot_beats"},
        {"id": "project_shoot", "source": "pitch_project", "target": "shoot_beats"},
        {"id": "photo_shoot", "source": "product_photo", "target": "shoot_beats"},
        {"id": "script_voice", "source": "pitch_script", "target": "voice_over"},
        {"id": "voice_place", "source": "voice_over", "target": "voice_on_timeline"},
        {"id": "project_voice_place", "source": "pitch_project", "target": "voice_on_timeline"},
        {"id": "shoot_export", "source": "shoot_beats", "target": "export_short"},
        {"id": "voice_export", "source": "voice_on_timeline", "target": "export_short"},
        {"id": "export_notice", "source": "export_short", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    return normalize_graph(
        {
            "meta": {"template_id": PRODUCT_PITCH_SHORT, "template_version": 1, "source": "official"},
            "nodes": nodes,
            "edges": edges,
        },
        node_types=NODE_TYPES,
    )


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
            "applications": {"type": "array", "items": application, "minItems": 1},
            "care_notes": _str("养护与工艺提示,中文;不确定的写「需与工厂确认」"),
        },
        ["spec_markdown", "applications", "care_notes"],
    )


def fabric_lookbook_graph(*, chat: Any, image: Any) -> dict[str, Any]:
    """一块面料 → 规划几种应用 → 每种出一张成品效果图 → 连同规格卡存成一页笔记。

    这是**给客户看的提案**,不是给平台发的内容:布料商最常被问的一句话是"这块布做成 X 长什么样",
    而他手里只有一张面料特写。所以交付物是「效果图 + 一页可以直接发出去的规格说明」。

    规格卡**只复述用户给的参数**。成分、克重、幅宽、缩率这些是要负责任的数字,编一个出来比不写更糟 ——
    提示词里写死了这一条,拿不准的一律写「需与工厂确认」。
    """
    system = """你是面料商的技术销售和陈列企划。客户给你一块面料的参数，你要做两件事：

1. 规划几种这块料**真的适合**的应用（家纺、服装、软装等），每种给一张成品效果图的英文提示词。
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
                    "fabric_name": "",
                    "composition": "成分,如 60% 棉 40% 亚麻",
                    "weight_gsm": "",
                    "width_cm": "",
                    "hand_feel": "手感与垂坠,一句话",
                    "target_client": "家纺采购 / 服装品牌",
                    "application_count": 4,
                }
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

{{fabric_plan.json.applications}}

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
                "body": "{{start.fabric_name}} 已出 {{render_applications.count}} 张应用效果图,规格页已存进笔记。",
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
            "meta": {"template_id": FABRIC_LOOKBOOK, "template_version": 1, "source": "official"},
            "nodes": nodes,
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
            "zh": "把一条口播、访谈或直播回放转成逐字稿,挑出能独立成立的片段,每条各建一条竖屏时间线、截取原片那一段、配上重写过的短句字幕并导出。不生成任何画面,所以除了转写和一次对话之外不花生成费用。",
            "en": "Transcribe a talk, interview or stream recording, pick the passages that stand on their own, then give each one its own vertical timeline, take that range from the source, lay rewritten short captions on it and export. No image or video generation, so nothing is billed beyond the transcription and one chat call.",
        },
        "requires": {
            "zh": ["可用的转写引擎", "AI 对话模型", "一条有人说话的长视频"],
            "en": ["Available transcription engine", "Chat model", "A long video with speech"],
        },
        "stages": {
            "zh": ["选择长视频", "生成带时间码逐字稿", "挑出能独立成立的片段", "逐条建竖屏时间线并截取", "配重写过的字幕", "逐条导出"],
            "en": ["Pick the long video", "Transcribe with timecodes", "Pick the passages that stand alone", "Give each its own vertical timeline", "Lay the rewritten captions", "Export each one"],
        },
    },
    {
        "id": PRODUCT_ON_MODEL,
        "name": {"zh": "商品图 → 模特上身图与短视频", "en": "Product photo into on-model shots"},
        "summary": {
            "zh": "给一张平铺图或面料图,规划几组投放场景,每组出一张模特上身图;视频模型可用时再把每一组动起来。商品图贯穿每一次生成 —— 版型、颜色、纹理、logo 都以它为准,不是照描述重画。卖点文案一并存成笔记。",
            "en": "From one flat-lay or fabric photo, plan a few sellable scenes and shoot an on-model image for each; where a video model is available, put every scene in motion too. The product photo is carried into every generation — cut, colour, texture and logo come from it, not from a description. The copy lines are saved as a note.",
        },
        "requires": {
            "zh": ["AI 对话模型", "能带参考图出图的图像模型(如 Seedream 4)", "一张商品平铺图或面料图", "短视频可选:支持首帧的视频模型"],
            "en": ["Chat model", "Image model that takes reference images (e.g. Seedream 4)", "A flat-lay or fabric photo", "Optional motion: a video model that takes a first frame"],
        },
        "stages": {
            "zh": ["描述商品与人群", "选择商品图", "规划几组投放场景", "逐组出模特上身图", "可选:逐组出短视频", "卖点文案存成笔记"],
            "en": ["Describe the product and audience", "Pick the product photo", "Plan the scenes", "Shoot each scene on a model", "Optional: put each scene in motion", "Save the copy as a note"],
        },
    },
    {
        "id": PRODUCT_PITCH_SHORT,
        "name": {"zh": "商品 → 带货口播短视频", "en": "Product into a talking-head short"},
        "summary": {
            "zh": "给一张商品图和几条卖点,写一条分拍的口播脚本,每一拍出一张带商品的画面、按这一拍的时长铺上时间线,配上口播与屏幕短句,导出竖屏成片。卖点只用你给的那几条,不编功效和数据。",
            "en": "From a product photo and a few selling points, write a beat-by-beat script, paint one frame per beat with the product in it, lay each on the timeline for that beat's length, add the voice-over and on-screen lines, and export a vertical short. Only the selling points you provide are used — no invented claims or figures.",
        },
        "requires": {
            "zh": ["AI 对话模型", "能带参考图出图的图像模型", "一把嗓子:配音库的克隆音色", "一张商品图"],
            "en": ["Chat model", "Image model that takes reference images", "A voice: a cloned voice from the voice library", "A product photo"],
        },
        "stages": {
            "zh": ["填商品与卖点", "写分拍口播脚本", "逐拍出画面并铺上时间线", "合成口播", "导出竖屏成片"],
            "en": ["Product and selling points", "Write the beat-by-beat script", "Paint each beat onto the timeline", "Synthesize the voice-over", "Export the vertical short"],
        },
    },
    {
        "id": FABRIC_LOOKBOOK,
        "name": {"zh": "面料 → 应用效果图与规格页", "en": "Fabric into applications and a spec sheet"},
        "summary": {
            "zh": "给一块面料的实拍图和参数,规划它真正适合做的几种成品,每种出一张放在真实空间里的效果图,并生成一页可直接发客户的规格与应用提案。规格只复述你给出的参数,没给的写「需与工厂确认」。",
            "en": "From one fabric photo and its specs, plan the products it genuinely suits, render each one in a real space, and produce a one-page proposal you can send to a client. The spec sheet only restates the numbers you provide; anything missing is marked as needing mill confirmation.",
        },
        "requires": {
            "zh": ["AI 对话模型", "能带参考图出图的图像模型", "一张面料实拍图"],
            "en": ["Chat model", "Image model that takes reference images", "A photo of the actual fabric"],
        },
        "stages": {
            "zh": ["填面料参数", "选择面料图", "规划应用与规格卡", "逐种出成品效果图", "生成可发客户的规格页"],
            "en": ["Fabric specs", "Pick the fabric photo", "Plan applications and the spec sheet", "Render each application", "Write the spec sheet to send"],
        },
    },
]
