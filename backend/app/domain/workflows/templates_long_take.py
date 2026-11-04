"""内置模板「任意长度的连续视频」:一段一段往下拍,接成一条不切镜头的长片。

视频模型一次最多出十几秒,要更长只能分段。段与段之间怎么接由模型能力定(见 `video_plan_for`):

- 收待续写片段(`first_clip`,万相 2.7、Seedance 续写、ComfyUI 的 H3 续写工作流)的,把上一段的尾巴交给下一段。
  成片以这段尾巴开头,上时间线时在画面里找到接缝,从那里接(`video_seam`)。`duration_seconds` 是含尾巴的总长;
- 只收首帧的,把上一段的最后一帧交给下一段。构图接得上,动作会顿一下。

第一段没有上一段可接,用另一个模型一格(`opening`)从文字出:续写模型多半做不了这件事。

**越拍越不像时拉回来。** 段段相接,走样也段段相传。模型收尾帧的,开始参数里可以设「每几段画一张锚点帧」:照上一段的最后
一帧和点名的资产画一张,当这一段的尾帧,这一段就落回人物本来的样子。默认不开,每张都是一次付费出图。

**生成和上时间线分成两个循环。** 重做某一段时,时间线清掉重新摆一遍,不会把新的一段接到旧的后面(见 ADR 0092 的重做)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import (
    CONTINUATION_TAIL_SECONDS,
    FRAME_ASPECTS,
    LATENT_CONTEXT_SECONDS,
    LATENT_SEGMENT_SECONDS,
    ModelChoice,
    VideoPlan,
    image_plan_for,
    video_plan_for,
)
from app.domain.workflows.templates_schemas import object_schema

LONG_TAKE_VIDEO = "long_take_video"


def _segments_schema() -> dict[str, Any]:
    text = {"type": "string"}
    return object_schema({"opening": text, "next": {"type": "array", "items": text}}, ["opening", "next"])


def _anchor_nodes(image: ModelChoice, plan: VideoPlan, db: Session | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """循环体里画锚点帧的那几个节点和它们的边:到了该画的那一轮才走(`anchor_due`),其余轮次整段跳过。"""
    size = image_plan_for(db, image).frame_sizes.get(plan.aspect_ratio)
    #: 交一段尾巴的还要从上一段取一帧;只交一帧的,交出去的那一帧就是。
    frame = "{{anchor_frame.asset_id}}" if plan.extends else "{{tail.asset_id}}"
    nodes: list[dict[str, Any]] = [
        {
            "id": "anchor_due", "type": "condition",
            "name": {"zh": "这一段要不要锚点帧", "en": "Does this segment get an anchor frame"},
            "position": {"x": 390, "y": -60},
            "config": {"left": "{{loop.index}}", "op": "every", "right": "{{input.anchor_every}}"},
        },
        {
            "id": "anchor", "type": "ai_generate",
            "name": {"zh": "画锚点帧", "en": "Paint the anchor frame"},
            "position": {"x": 1010, "y": -60},
            "config": {
                "provider": image.provider, "provider_profile_id": image.profile_id, "model": image.model, "kind": "image",
                "prompt": "{{input.style}} {{loop.item.beat}} The last moment of this shot: same place, light and camera as the "
                          "reference frame, sharp and clean, with every named character exactly as in their references.",
                "parameters": {"size": size} if size else {},
                "source_assets": [f"{frame}:reference_image"],
                "entity_ids": "{{input.entity_ids}}",
            },
        },
    ]
    edges = [
        {"id": "tail_anchor_due", "source": "tail", "target": "anchor_due"},
        {"id": "anchor_extend", "source": "anchor", "target": "extend"},
    ]
    if plan.extends:
        nodes.append({
            "id": "anchor_frame", "type": "video_frame",
            "name": {"zh": "取上一段的最后一帧", "en": "Take the last frame of the previous segment"},
            "position": {"x": 700, "y": -60},
            "config": {"asset_id": "{{loop.previous}}"},
        })
        edges += [
            {"id": "anchor_due_frame", "source": "anchor_due", "target": "anchor_frame", "source_handle": "true"},
            {"id": "anchor_frame_paint", "source": "anchor_frame", "target": "anchor"},
        ]
    else:
        edges.append({"id": "anchor_due_paint", "source": "anchor_due", "target": "anchor", "source_handle": "true"})
    return nodes, edges


def long_take_video_graph(*, chat: ModelChoice, opening: ModelChoice, video: ModelChoice,
                          image: ModelChoice | None = None, db: Session | None = None) -> dict[str, Any]:
    plan = video_plan_for(db, video, references=0)
    #: 模型不收尾帧、或者这台机器上没有收参考图的图片模型:没有这一格,图里也没有这几个节点。
    anchors = plan.last_frame and image is not None and bool(image.model)
    anchor_nodes, anchor_edges = _anchor_nodes(image, plan, db) if anchors else ([], [])
    first_plan = video_plan_for(db, opening, references=0)
    width, height = FRAME_ASPECTS.get(plan.aspect_ratio, FRAME_ASPECTS["16:9"])
    parameters = dict(plan.parameters or {})
    first_parameters = dict(first_plan.parameters or {})
    #: 循环体里只看得见 `input`,外面的值经容器的输入传进去。
    if "duration_seconds" in parameters:
        parameters["duration_seconds"] = "{{input.segment_seconds}}"
    if "duration_seconds" in first_parameters:
        first_parameters["duration_seconds"] = "{{input.segment_seconds}}"
    #: 出片计划写的是 `input.*`(给循环体用);第一段在顶层,读开始参数。
    first_parameters = {key: value.replace("{{input.", "{{start.") if isinstance(value, str) else value
                        for key, value in first_parameters.items()}
    #: 清晰度的写法各家不同(万相 `720P`、Seedance `720p`):开始参数那一格是续写模型的,写法不同的第一段写它自己的。
    if "resolution" in first_parameters and opening.provider != video.provider:
        first_parameters["resolution"] = first_plan.resolution
    if plan.latent_chain:
        #: 段与段接在潜空间里:读上一段、存这一段,不用截尾巴。文件夹按项目分,一次运行一份。
        parameters.update({"50.project_folder": "{{input.latent_folder}}", "50.scene_number": "{{loop.item.previous_scene}}",
                           "52.project_folder": "{{input.latent_folder}}", "52.scene_number": "{{loop.item.scene}}"})
        first_parameters.update({"52.project_folder": "mosael/{{video_project.project_id}}", "52.scene_number": 1})
    if plan.extends:
        tail_node: dict[str, Any] = {
            "id": "tail", "type": "media_clip",
            "name": {"zh": "取上一段的尾巴", "en": "Take the tail of the previous segment"},
            "position": {"x": 80, "y": 140},
            "config": {"asset_id": "{{loop.previous}}", "last_seconds": "{{input.overlap_seconds}}"},
        }
        handed_over = "{{tail.asset_id}}:first_clip"
    else:
        tail_node = {
            "id": "tail", "type": "video_frame",
            "name": {"zh": "取上一段的最后一帧", "en": "Take the last frame of the previous segment"},
            "position": {"x": 80, "y": 140},
            "config": {"asset_id": "{{loop.previous}}"},
        }
        handed_over = "{{tail.asset_id}}:first_frame"
    segment_body = {
        "nodes": [
            *([] if plan.latent_chain else [tail_node]),
            {
                "id": "extend", "type": "ai_generate",
                "name": {"zh": "接着往下拍", "en": "Carry on from there"},
                "position": {"x": 390, "y": 140},
                "config": {
                    "provider": video.provider, "provider_profile_id": video.profile_id, "model": video.model, "kind": "video",
                    #: 只写「接着发生什么」时,模型会切到那个地方、人也换一个样子(实测 H3 每段都在尾巴结束处硬切)。
                    #: 每段都带上开场那段:同一个人、同一个地方,这一段只往前走一点。
                    "prompt": "{{input.style}} {{input.scene}} One continuous shot with no cut, the same person in the same "
                              "place, carrying on from the given clip. What happens now: {{loop.item.beat}}",
                    "parameters": parameters,
                    "source_assets": [] if plan.latent_chain else [handed_over, *(["{{anchor.asset_id}}:last_frame"] if anchors else [])],
                    "entity_ids": "{{input.entity_ids}}",
                },
            },
            *anchor_nodes,
        ],
        "edges": [] if plan.latent_chain else [{"id": "tail_extend", "source": "tail", "target": "extend"}, *anchor_edges],
    }
    append_segment: dict[str, Any] = {
        "id": "append_segment", "type": "timeline_append",
        "name": {"zh": "接到时间线上", "en": "Add it to the timeline"},
        "position": {"x": 390, "y": 140},
        "config": {
            "sequence_id": "{{input.sequence_id}}",
            "asset_id": "{{loop.item}}",
            #: 成片以交过去的那段尾巴开头:这一截上一段已经有了。只交了一帧的不用去掉。潜空间的上文长度是准的,不用在画面里找。
            "start": "{{input.overlap_seconds}}" if plan.latent_chain else "{{seam.start}}" if plan.extends else 0,
        },
    }
    seam: dict[str, Any] = {
        "id": "seam", "type": "video_seam",
        "name": {"zh": "找接缝", "en": "Find the seam"},
        "position": {"x": 80, "y": 140},
        "config": {
            "previous_asset_id": "{{loop.previous}}",
            "asset_id": "{{loop.item}}",
            #: 尾巴可能被拉长或压缩,多找一截。
            "search_seconds": "{{input.search_seconds}}",
        },
    }
    assemble_body = {
        "nodes": [seam, append_segment] if plan.extends and not plan.latent_chain else [append_segment],
        "edges": [{"id": "seam_append", "source": "seam", "target": "append_segment"}] if plan.extends and not plan.latent_chain else [],
    }
    graph: dict[str, Any] = {
        "meta": {"template_id": LONG_TAKE_VIDEO, "template_version": 6, "source": "official"},
        "nodes": [
            {
                "id": "start", "type": "start",
                "name": {"zh": "开始", "en": "Start"},
                "position": {"x": 40, "y": 300},
                "config": {
                    "params": {
                        "idea": "",
                        "target_seconds": 60,
                        #: 收待续写片段的按最长的拍:每段都有一截重叠,段越长浪费的比例越小。
                        "segment_seconds": LATENT_SEGMENT_SECONDS if plan.latent_chain else
                        plan.longest_clip if plan.extends and plan.longest_clip else plan.clip_seconds,
                        "overlap_seconds": LATENT_CONTEXT_SECONDS if plan.latent_chain else plan.tail_seconds or CONTINUATION_TAIL_SECONDS,
                        #: 成本的闸门:每一段都是一次付费生成。超过的段不跑。
                        "max_segments": 12,
                        #: 累计花到这个数就停,0 是不限。停下之后调高它再点「从中断处继续」。
                        "max_spend": 0,
                        "style": "",
                        #: 点名的资产(人物、场景,逗号分隔):每一段都带上它们,防止越拍越不像。模型不收参考时生成回执会说。
                        "entity_ids": "",
                        #: 每几段画一张锚点帧把人物拉回来,0 是不画。
                        **({"anchor_every": 0} if anchors else {}),
                        "aspect_ratio": plan.aspect_ratio,
                        "resolution": plan.resolution,
                    },
                    "required_params": ["idea"],
                },
            },
            {
                #: 段数由这里算,不靠模型心算:只说「总时长约多少」时它交回过空的 next,要 18 秒的片子只出了第一段(实测)。
                "id": "plan", "type": "chain_plan",
                "name": {"zh": "算要拍几段", "en": "Work out how many segments"},
                "position": {"x": 40, "y": 620},
                "config": {
                    "target_seconds": "{{start.target_seconds}}",
                    "longest_seconds": "{{start.segment_seconds}}",
                    "overlap_seconds": "{{start.overlap_seconds}}",
                },
            },
            {
                "id": "split", "type": "llm",
                "name": {"zh": "把想法拆成一段一段", "en": "Split the idea into segments"},
                "position": {"x": 340, "y": 300},
                "config": {
                    "profile_id": chat.profile_id, "model": chat.model, "preset": "precise",
                    "system": "你是分镜导演。这是一条不切镜头的连续长片,一段接一段往下拍:同一场景、同一人物、同一机位逻辑。"
                              "只写下一段**接着发生什么**,不重复外观描述,不写切镜、转场。用英文写,每段一两句。",
                    "prompt": "想法:{{start.idea}}\n总时长约 {{start.target_seconds}} 秒,每段 {{start.segment_seconds}} 秒。"
                              "opening 写第一段(要交代人物、场景、光线、机位),next 写后面每一段:"
                              "**next 要写满 {{plan.following}} 段**,超过 {{start.max_segments}} 段时写到这个数为止。",
                    "response_format": "json_schema",
                    "json_schema_name": "long_take_segments",
                    "json_schema": _segments_schema(),
                    "json_schema_strict": "true",
                    "temperature": 0.6,
                    "max_tokens": 16000,
                },
            },
            {
                #: 段数以 `plan` 为准;语言模型写的这几段铺到每一段上,写少了也不缩水。
                "id": "beats", "type": "chain_plan",
                "name": {"zh": "把每段要演的铺开", "en": "Spread the beats over the segments"},
                "position": {"x": 340, "y": 620},
                "config": {
                    "target_seconds": "{{start.target_seconds}}",
                    "longest_seconds": "{{start.segment_seconds}}",
                    "overlap_seconds": "{{start.overlap_seconds}}",
                    "beats": "{{split.json.next}}",
                },
            },
            {
                "id": "estimate", "type": "video_cost_estimate",
                "name": {"zh": "估算费用", "en": "Estimate the cost"},
                "position": {"x": 660, "y": 620},
                "config": {
                    "provider": video.provider, "provider_profile_id": video.profile_id, "model": video.model,
                    "items": "{{beats.rounds}}", "extra_items": 1,
                    "seconds_each": "{{start.segment_seconds}}",
                    "resolution": plan.resolution,
                    "max_spend": "{{start.max_spend}}",
                },
            },
            {
                "id": "video_project", "type": "project_sequence_create",
                "name": {"zh": "建立项目与时间线", "en": "Create the project and timeline"},
                "position": {"x": 660, "y": 120},
                "config": {"name": "长片", "width": width, "height": height, "fps": 24},
            },
            {
                "id": "opening", "type": "ai_generate",
                "name": {"zh": "拍第一段", "en": "Shoot the first segment"},
                "position": {"x": 660, "y": 420},
                "config": {
                    "provider": opening.provider, "provider_profile_id": opening.profile_id, "model": opening.model, "kind": "video",
                    "prompt": "{{start.style}} {{split.json.opening}}",
                    "parameters": first_parameters,
                    "entity_ids": "{{start.entity_ids}}",
                },
            },
            {
                "id": "segments", "type": "loop_foreach",
                "name": {"zh": "一段接一段往下拍", "en": "Shoot segment after segment"},
                "position": {"x": 980, "y": 420},
                "config": {
                    "items": "{{beats.rounds}}",
                    "inputs": {
                        "style": "{{start.style}}",
                        "scene": "{{split.json.opening}}",
                        **({"latent_folder": "mosael/{{video_project.project_id}}"} if plan.latent_chain else {}),
                        "overlap_seconds": "{{start.overlap_seconds}}",
                        "segment_seconds": "{{start.segment_seconds}}",
                        "entity_ids": "{{start.entity_ids}}",
                        **({"anchor_every": "{{start.anchor_every}}"} if anchors else {}),
                        "aspect_ratio": "{{start.aspect_ratio}}",
                        "resolution": "{{start.resolution}}",
                    },
                    "body": segment_body,
                    "output": "{{extend.asset_id}}",
                    "previous_initial": "{{opening.asset_id}}",
                    "max_items": "{{start.max_segments}}",
                    "max_spend": "{{start.max_spend}}",
                },
            },
            {
                "id": "clear_timeline", "type": "timeline_clear",
                "name": {"zh": "清空时间线", "en": "Clear the timeline"},
                "position": {"x": 1300, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}"},
            },
            {
                "id": "append_opening", "type": "timeline_append",
                "name": {"zh": "摆上第一段", "en": "Lay down the first segment"},
                "position": {"x": 1600, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}", "asset_id": "{{opening.asset_id}}"},
            },
            {
                "id": "assemble", "type": "loop_foreach",
                "name": {"zh": "把后面每一段接上去", "en": "Add every later segment"},
                "position": {"x": 1900, "y": 300},
                "config": {
                    "items": "{{segments.results}}",
                    "inputs": {"sequence_id": "{{video_project.sequence_id}}", "search_seconds": "{{start.segment_seconds}}",
                               "overlap_seconds": "{{start.overlap_seconds}}"},
                    "body": assemble_body,
                    "output": "{{loop.item}}",
                    "previous_initial": "{{opening.asset_id}}",
                },
            },
            {
                "id": "export_final", "type": "export_sequence",
                "name": {"zh": "导出成片", "en": "Export the finished video"},
                "position": {"x": 2200, "y": 300},
                "config": {"sequence_id": "{{video_project.sequence_id}}"},
            },
            {
                "id": "output", "type": "output",
                "name": {"zh": "交付成片", "en": "Hand over the finished video"},
                "position": {"x": 2500, "y": 300},
                "config": {"values": {"video_asset_id": "{{export_final.asset_id}}", "segments": "{{segments.results}}"}},
            },
        ],
        "edges": [
            {"id": "start_plan", "source": "start", "target": "plan"},
            {"id": "plan_split", "source": "plan", "target": "split"},
            {"id": "split_project", "source": "split", "target": "video_project"},
            {"id": "project_opening", "source": "video_project", "target": "opening"},
            {"id": "split_beats", "source": "split", "target": "beats"},
            {"id": "beats_estimate", "source": "beats", "target": "estimate"},
            {"id": "estimate_opening", "source": "estimate", "target": "opening"},
            {"id": "opening_segments", "source": "opening", "target": "segments"},
            {"id": "segments_clear", "source": "segments", "target": "clear_timeline"},
            {"id": "clear_opening", "source": "clear_timeline", "target": "append_opening"},
            {"id": "opening_assemble", "source": "append_opening", "target": "assemble"},
            {"id": "assemble_export", "source": "assemble", "target": "export_final"},
            {"id": "export_output", "source": "export_final", "target": "output"},
        ],
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
