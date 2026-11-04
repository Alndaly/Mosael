"""内置模板「任意长度的连续视频」:一段一段往下拍,接成一条不切镜头的长片。

视频模型一次最多出十几秒,要更长只能分段。段与段之间怎么接由模型能力定(见 `video_plan_for`):

- 收待续写片段(`first_clip`,万相 2.7、Seedance 续写、ComfyUI 的 H3 续写工作流)的,把上一段的尾巴交给下一段。
  成片以这段尾巴开头,上时间线时在画面里找到接缝,从那里接(`video_seam`)。`duration_seconds` 是含尾巴的总长;
- 只收首帧的,把上一段的最后一帧交给下一段。构图接得上,动作会顿一下。

第一段没有上一段可接,用另一个模型一格(`opening`)从文字出:续写模型多半做不了这件事。

**生成和上时间线分成两个循环。** 重做某一段时,时间线清掉重新摆一遍,不会把新的一段接到旧的后面(见 ADR 0092 的重做)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import FRAME_ASPECTS, ModelChoice, video_plan_for
from app.domain.workflows.templates_schemas import object_schema

LONG_TAKE_VIDEO = "long_take_video"

#: 尾巴留多长。H3 按 17k+5 帧取片段,22 帧正好是 24fps 下的 0.92 秒:写成 1 秒的话多出来的两帧被裁掉,时间线上差两帧。
OVERLAP_SECONDS = 0.92


def _segments_schema() -> dict[str, Any]:
    text = {"type": "string"}
    return object_schema({"opening": text, "next": {"type": "array", "items": text}}, ["opening", "next"])


def long_take_video_graph(*, chat: ModelChoice, opening: ModelChoice, video: ModelChoice, db: Session | None = None) -> dict[str, Any]:
    plan = video_plan_for(db, video, references=0)
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
            tail_node,
            {
                "id": "extend", "type": "ai_generate",
                "name": {"zh": "接着往下拍", "en": "Carry on from there"},
                "position": {"x": 390, "y": 140},
                "config": {
                    "provider": video.provider, "provider_profile_id": video.profile_id, "model": video.model, "kind": "video",
                    "prompt": "{{input.style}} {{loop.item}}",
                    "parameters": parameters,
                    "source_assets": [handed_over],
                    "entity_ids": "{{input.entity_ids}}",
                },
            },
        ],
        "edges": [{"id": "tail_extend", "source": "tail", "target": "extend"}],
    }
    append_segment: dict[str, Any] = {
        "id": "append_segment", "type": "timeline_append",
        "name": {"zh": "接到时间线上", "en": "Add it to the timeline"},
        "position": {"x": 390, "y": 140},
        "config": {
            "sequence_id": "{{input.sequence_id}}",
            "asset_id": "{{loop.item}}",
            #: 成片以交过去的那段尾巴开头:这一截上一段已经有了。只交了一帧的不用去掉。
            "start": "{{seam.start}}" if plan.extends else 0,
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
        "nodes": [seam, append_segment] if plan.extends else [append_segment],
        "edges": [{"id": "seam_append", "source": "seam", "target": "append_segment"}] if plan.extends else [],
    }
    graph: dict[str, Any] = {
        "meta": {"template_id": LONG_TAKE_VIDEO, "template_version": 3, "source": "official"},
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
                        "segment_seconds": plan.longest_clip if plan.extends and plan.longest_clip else plan.clip_seconds,
                        "overlap_seconds": max(OVERLAP_SECONDS, plan.shortest_tail),
                        #: 成本的闸门:每一段都是一次付费生成。超过的段不跑。
                        "max_segments": 12,
                        #: 累计花到这个数就停,0 是不限。停下之后调高它再点「从中断处继续」。
                        "max_spend": 0,
                        "style": "",
                        #: 点名的资产(人物、场景,逗号分隔):每一段都带上它们,防止越拍越不像。模型不收参考时生成回执会说。
                        "entity_ids": "",
                        "aspect_ratio": plan.aspect_ratio,
                        "resolution": plan.resolution,
                    },
                    "required_params": ["idea"],
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
                    "prompt": "想法:{{start.idea}}\n总时长约 {{start.target_seconds}} 秒,每段 {{start.segment_seconds}} 秒,"
                              "最多 {{start.max_segments}} 段。opening 写第一段(要交代人物、场景、光线、机位),next 写后面每一段。",
                    "response_format": "json_schema",
                    "json_schema_name": "long_take_segments",
                    "json_schema": _segments_schema(),
                    "json_schema_strict": "true",
                    "temperature": 0.6,
                    "max_tokens": 4000,
                },
            },
            {
                "id": "estimate", "type": "video_cost_estimate",
                "name": {"zh": "估算费用", "en": "Estimate the cost"},
                "position": {"x": 660, "y": 620},
                "config": {
                    "provider": video.provider, "provider_profile_id": video.profile_id, "model": video.model,
                    "items": "{{split.json.next}}", "extra_items": 1,
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
                    "items": "{{split.json.next}}",
                    "inputs": {
                        "style": "{{start.style}}",
                        "overlap_seconds": "{{start.overlap_seconds}}",
                        "segment_seconds": "{{start.segment_seconds}}",
                        "entity_ids": "{{start.entity_ids}}",
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
                    "inputs": {"sequence_id": "{{video_project.sequence_id}}", "search_seconds": "{{start.segment_seconds}}"},
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
            {"id": "start_split", "source": "start", "target": "split"},
            {"id": "split_project", "source": "split", "target": "video_project"},
            {"id": "split_estimate", "source": "split", "target": "estimate"},
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
