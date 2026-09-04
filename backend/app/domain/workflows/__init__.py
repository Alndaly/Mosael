"""工作流内核(Coze/Dify 式)。

一个工作流 = 节点(nodes) + 连线(edges) 的 DAG,存为 JSON graph:

    {
      "nodes": [{"id": "n1", "type": "start", "name": "wfNode_start",
                  "position": {"x": 0, "y": 0}, "config": {...}}, ...],
      "edges": [{"id": "e1", "source": "n1", "target": "n2"}, ...]
    }

节点 config 里的字符串支持 `{{节点id.输出名}}` 变量引用,执行时按拓扑序
求值。定时任务与智能体都以工作流为执行单元。
"""

from __future__ import annotations

from app.domain.generation.catalog import BUILTIN_MODELS, SOURCE_ROLE_LABELS
from app.domain.sequences.operations import EDIT_OP_KINDS

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workflow


def _source_assets_help() -> dict[str, str]:
    """「AI 生成素材」节点里那句关于角色的说明所需的**参数**,从描述符生成。

    它此前是手写的一串,而 catalog 里的 SOURCE_ROLE_LABELS 才是这份知识的产地 ——
    那张表的注释已经预言了这件事:「此前这张表存在三份…新增角色时漏掉哪一份都不会报错,
    只是智能体不知道有这个东西,于是永远不会用它」。工作流节点这段就是仍然活着的第四份:
    今天八种角色恰好写全了,而加第九种时不会有任何东西提醒你回来补这句话。

    **它返回的是参数,不是句子。** 句子在出口按语言组装(见 core/i18n 里的
    wfNode_ai_generate_source_assets)—— 领域不该知道读它的人看哪种语言。角色**两种语言
    都跟着这张表走**:加第九种时,两句话同时变,而不是只有中文那句变。
    """
    return {
        #: 英文那句用逗号 —— 顿号是中文标点,混在英文句子里读起来是坏的。
        "roles": ", ".join(SOURCE_ROLE_LABELS),
        "roles_zh": "、".join(f"{role} {label}" for role, label in SOURCE_ROLE_LABELS.items()),
    }


def _generation_parameters_help() -> dict[str, str]:
    """同上:可用的生成参数按目录里**实际出现过的**键列出,不手抄。

    同样只返回参数:句子在出口按语言组装。末尾那句「查这个模型的 capabilities」在两种
    语言的模板里都有 —— 因为哪些键可用是**逐模型**的,这里能给的只是全集。
    """
    keys = sorted(
        key
        for model in BUILTIN_MODELS
        for key in model["capabilities"].get("parameter_keys", ())
        if key not in SOURCE_ROLE_LABELS
    )
    return {"keys": " / ".join(dict.fromkeys(keys))}


class WorkflowDomainError(RuntimeError):
    """可安全展示给工作流操作者的领域错误。

    ``details`` 是给任务事件/历史界面的结构化诊断，不拼进短错误文案。这样列表仍然可读，
    同时失败现场（例如 LLM 的真实响应）不会在异常跨过执行线程时被丢掉。
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# 节点类型注册表:同时驱动后端校验、前端节点面板和智能体的图编辑提示。
# outputs 是节点执行后写入上下文的键;config 描述每个可配置字段。
#: 配置项可以标 `"advanced": True`。
#:
#: 判据是「留空也能把这个节点跑起来吗」——能,就是高级项。编辑器把它们收进折叠的「高级选项」,
#: 不在用户第一眼就把十几个采样参数糊到脸上;AI 助手也读同一份声明,不会替用户瞎填。
#: 反过来:required 的、以及决定这个节点在做什么的字段(提示词、模型、URL),永远留在外面。

#: 节点面板的分组与**顺序**。节点类型注册表里每一项都必须落在其中一组(有测试钉着)。
#:
#: 顺序不是随手排的,它是一条搭工作流的动线:先有骨架(流程),再决定这一步做什么
#: (AI / 素材 / 数据),然后是把结果送出去(发布),最后才是两类"需要额外准备"的能力 ——
#: 浏览器要登录态,插件要先装。列表顺序即面板顺序,前端不再排第二次。
#: 分组名也存 key —— 它出现在节点面板的每一栏标题上,写死的话英文界面下那几栏还是中文。
NODE_CATEGORIES: tuple[str, ...] = (
    "wfCat_flow",
    "wfCat_ai",
    "wfCat_asset",
    "wfCat_data",
    "wfCat_publish",
    "wfCat_browser",
    "wfCat_plugin",
)

#: 一个 object 字段该用**哪种编辑器**。
#:
#: 绝大多数 object 配置其实是「名字 → 值」的映射:入参映射、请求头、具名输出、启动参数……
#: 值往往还是上游节点的引用(`{{llm-1.text}}`)。让用户对着一个 `{}` 手写 JSON,要背键名、
#: 要记引号逗号,而**写错了直到运行才知道**。这类字段给一行一对的编辑器,值那格能从上游输出里挑。
#:
#: 只有真正是自由结构的才留原始 JSON —— 目前就 `json_schema` 一个(它是一份 schema,
#: 天然嵌套,拍平成键值对是错的)。所以默认给 map,例外自己声明 `"editor": "json"` ——
#: 这样新加的 object 字段自动就有友好编辑器,而不是等谁记得来补。
_RAW_JSON_FIELDS = {"json_schema"}


def config_editor(key: str, spec: dict[str, Any]) -> str:
    """这个字段用哪种编辑器:map(一行一对)/ json(原始 JSON)/ 空(非 object,按类型走)。"""
    if str(spec.get("type") or "") != "object":
        return ""
    explicit = str(spec.get("editor") or "").strip()
    if explicit:
        return explicit
    return "json" if key in _RAW_JSON_FIELDS else "map"


#: 配置字段在界面上**叫什么**。
#:
#: 这份知识此前是前端手抄的一张表(WorkflowsView 的 FIELD_LABEL_KEYS),81 个键里只覆盖了 28 个
#: —— 剩下 55 个在中文界面上直接显示英文键名:`session`、`selector`、`timeout_ms`、
#: `temperature`…… 而且**插件节点永远不可能被那张表覆盖**,它们是运行时才知道的。
#:
#: 今天这是第三次撞见同一个形状了(智能体的角色表、字段类型表、现在是标签表):一份该住在
#: 声明里的知识,被抄到了消费方那边,于是加东西时漏掉不报错,只是界面上默默露出一个英文单词。
#:
#: 配置字段和输出接点共享的**语义名字典**。连线和执行始终使用稳定的英文键,
#: 人机界面才把键映射成当前语言的显示名。按键名给、不按节点给,避免 `sequence_id`
#: 在每个时间线节点里各写一次后慢慢分叉。特殊语义可用节点自己的 label 覆盖。
_FIELD_LABELS = {
    "account_id": "wfField_account_id",
    "all": "wfField_all",
    "asset_id": "wfField_asset_id",
    "asset_ids": "wfField_asset_ids",
    "clip_id": "wfField_clip_id",
    "attribute": "wfField_attribute",
    "body": "wfField_body",
    "code": "wfField_code",
    "condition": "wfField_condition",
    "description": "wfField_description",
    "duration": "wfField_duration",
    "dy": "wfField_dy",
    "end": "wfField_end",
    "engine": "wfField_engine",
    "exact": "wfField_exact",
    "expression": "wfField_expression",
    "file_path": "wfField_file_path",
    "find": "wfField_find",
    "fps": "wfField_fps",
    "frequency_penalty": "wfField_frequency_penalty",
    "gone": "wfField_gone",
    "headers": "wfField_headers",
    "height": "wfField_height",
    "input": "wfField_input",
    "inputs": "wfField_inputs",
    "instance_id": "wfField_instance_id",
    "items": "wfField_items",
    "json_schema": "wfField_json_schema",
    "json_schema_name": "wfField_json_schema_name",
    "json_schema_strict": "wfField_json_schema_strict",
    "kind": "wfField_kind",
    "left": "wfField_left",
    "limit": "wfField_limit",
    "max_removal_ratio": "wfField_max_removal_ratio",
    "max_iterations": "wfField_max_iterations",
    "max_tokens": "wfField_max_tokens",
    "method": "wfField_method",
    "min_confidence": "wfField_min_confidence",
    "mode": "wfField_mode",
    "model": "wfField_model",
    "name": "wfField_name",
    "name_contains": "wfField_name_contains",
    "negative_prompt": "wfField_negative_prompt",
    "op": "wfField_op",
    "operations": "wfField_operations",
    "output": "wfField_output",
    "parameters": "wfField_parameters",
    "params": "wfField_params",
    "path": "wfField_path",
    "plugin_id": "wfField_plugin_id",
    "presence_penalty": "wfField_presence_penalty",
    "preset": "wfField_preset",
    "profile_id": "wfField_profile_id",
    "project_id": "wfField_project_id",
    "prompt": "wfField_prompt",
    "provider": "wfField_provider",
    "replace": "wfField_replace",
    "ranges": "wfField_ranges",
    "response_format": "wfField_response_format",
    "right": "wfField_right",
    "seconds": "wfField_seconds",
    "seed": "wfField_seed",
    "selector": "wfField_selector",
    "sequence_id": "wfField_sequence_id",
    "session": "wfField_session",
    "session_mode": "wfField_session_mode",
    "session_name": "wfField_session_name",
    "source": "wfField_source",
    "source_assets": "wfField_source_assets",
    "start": "wfField_start",
    "stop": "wfField_stop",
    "system": "wfField_system",
    "tags": "wfField_tags",
    "target_lang": "wfField_target_lang",
    "temperature": "wfField_temperature",
    "template": "wfField_template",
    "text": "wfField_text",
    "timeout_ms": "wfField_timeout_ms",
    "title": "wfField_title",
    "tool_name": "wfField_tool_name",
    "top_p": "wfField_top_p",
    "track_id": "wfField_track_id",
    "url": "wfField_url",
    "url_contains": "wfField_url_contains",
    "value": "wfField_value",
    "values": "wfField_values",
    "voice_id": "wfField_voice_id",
    "workflow_id": "wfField_workflow_id",
    "width": "wfField_width",
    # 下列主要出现在输出端,也可被同名配置字段复用。
    "applied": "wfField_applied",
    "assets": "wfField_assets",
    "audio_track_id": "wfField_audio_track_id",
    "count": "wfField_count",
    "generation_id": "wfField_generation_id",
    "ids": "wfField_ids",
    "iterations": "wfField_iterations",
    "json": "wfField_json",
    "language": "wfField_language",
    "length": "wfField_length",
    "removed": "wfField_removed",
    "removed_seconds": "wfField_removed_seconds",
    "result": "wfField_result",
    "results": "wfField_results",
    "revision": "wfField_revision",
    "segments": "wfField_segments",
    "sent": "wfField_sent",
    "source_asset_id": "wfField_source_asset_id",
    "status": "wfField_status",
    "timed_text": "wfField_timed_text",
    "timeline_end": "wfField_timeline_end",
    "timeline_start": "wfField_timeline_start",
    "tracks": "wfField_tracks",
    "transcript_id": "wfField_transcript_id",
    "updated": "wfField_updated",
    "video_track_id": "wfField_video_track_id",
    "waited": "wfField_waited",
}


def _humanize_field_key(key: str) -> str:
    """不认识的插件字段也不直接暴露 snake_case。

    内置语义都由 _FIELD_LABELS 翻译;这里只是第三方声明不完整时的可读降级。
    """
    words = key.removeprefix("*").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else key


def config_label(key: str, spec: dict[str, Any]) -> str:
    """这个配置字段在界面上叫什么。"""
    explicit = str(spec.get("label") or "").strip()
    return explicit or _FIELD_LABELS.get(key, "") or _humanize_field_key(key)


def output_label(key: str, node_spec: dict[str, Any]) -> str:
    """输出接点的显示名;英文 key 本身仍是连线与序列化契约。"""
    declared = node_spec.get("output_labels")
    explicit = str(declared.get(key) or "").strip() if isinstance(declared, dict) else ""
    canonical = key.removeprefix("*")
    return explicit or _FIELD_LABELS.get(canonical, "") or _humanize_field_key(key)


#: 一个配置字段**装的是什么东西** —— 素材?时间线?还是随便什么值。
#:
#: 界面靠它决定给不给素材选择器、画不画缩略图、连线时类型对不对得上。此前这张表是**前端
#: 自己抄的一份**(features/workflows/analyze.ts 的 INPUT_TYPES),于是:
#:
#:   · 「素材」节点本身就漏了 —— 它整个存在的意义就是指向一份素材,却拿不到素材选择器,
#:     用户只能手打一串十六进制;
#:   · 插件节点**永远**不可能被那张表覆盖,它们是运行时才知道的;
#:   · 新加一种节点,忘了改前端那张表不会报错,只是安静地少了选择器和校验。
#:
#: 所以改成**按字段名推**,而不是逐个登记:沿用 asset_id / sequence_id 这套既有命名的新节点
#: 自动就有这些能力,不需要谁记得去补一张表。要覆盖的话在 spec 里显式写 data_type。
_DATA_TYPE_BY_NAME = (
    ("asset_ids", "asset"),
    ("asset_id", "asset"),
    ("sequence_id", "sequence"),
)


def config_data_type(key: str, spec: dict[str, Any]) -> str:
    """这个配置字段装的是什么。推不出来就返回空串(界面按"随便什么值"处理)。"""
    explicit = str(spec.get("data_type") or "").strip()
    if explicit:
        return explicit
    for name, data_type in _DATA_TYPE_BY_NAME:
        if key == name or key.endswith(f"_{name}"):
            return data_type
    return ""


_OUTPUT_DATA_TYPES = {
    "applied": "number",
    "count": "number",
    "duration": "number",
    "iterations": "number",
    "json": "json",
    "length": "number",
    "removed": "number",
    "revision": "number",
    "status": "number",
    "text": "text",
    "timeline_end": "number",
    "timeline_start": "number",
    "waited": "number",
}
_WORKFLOW_DATA_TYPES = frozenset({"text", "asset", "sequence", "number", "json", "any"})


def output_data_type(key: str, node_spec: dict[str, Any]) -> str:
    """Return the declared semantic type for one node output, always with an ``any`` fallback."""

    declared = node_spec.get("output_types")
    if isinstance(declared, dict):
        explicit = str(declared.get(key) or "").strip()
        if explicit in _WORKFLOW_DATA_TYPES:
            return explicit
    if key == "asset_id" or key.endswith("_asset_id"):
        return "asset"
    if key == "sequence_id" or key.endswith("_sequence_id"):
        return "sequence"
    return _OUTPUT_DATA_TYPES.get(key, "any")


NODE_TYPES: dict[str, dict[str, Any]] = {
    "start": {
        "category": "wfCat_flow",
        "label": "wfNode_start",
        "description": "wfNode_start_desc",
        "config": {"params": {"type": "object", "description": "wfNode_start_params"}},
        "outputs": ["*params"],
    },
    "llm": {
        "category": "wfCat_ai",
        "label": "wfNode_llm",
        "description": "wfNode_llm_desc",
        "config": {
            "prompt": {"type": "template", "required": True, "description": "wfNode_llm_prompt"},
            "system": {"type": "template"},
            "preset": {
                "type": "string",
                "description": "wfNode_llm_preset",
                "options": ["precise", "balanced", "creative"],
            },
            "profile_id": {"type": "string", "description": "wfNode_llm_profile_id"},
            "model": {"type": "string", "description": "wfNode_llm_model", "depends_on": "profile_id"},
            "temperature": {"advanced": True, "type": "number", "description": "wfNode_llm_temperature"},
            "top_p": {"advanced": True, "type": "number", "description": "wfNode_llm_top_p"},
            "max_tokens": {"advanced": True, "type": "number", "description": "wfNode_llm_max_tokens"},
            "frequency_penalty": {"advanced": True, "type": "number", "description": "wfNode_llm_frequency_penalty"},
            "presence_penalty": {"advanced": True, "type": "number", "description": "wfNode_llm_presence_penalty"},
            "seed": {"advanced": True, "type": "number", "description": "wfNode_llm_seed"},
            "stop": {"advanced": True, "type": "template", "description": "wfNode_llm_stop"},
            "response_format": {"advanced": True, 
                "type": "string",
                "description": "wfNode_llm_response_format",
                "options": ["text", "json_object", "json_schema"],
            },
            "json_schema_name": {"advanced": True, "type": "template", "description": "wfNode_llm_json_schema_name"},
            "json_schema": {"advanced": True, "type": "object", "description": "wfNode_llm_json_schema"},
            "json_schema_strict": {"advanced": True, 
                "type": "string",
                "description": "wfNode_llm_json_schema_strict",
                "options": ["true", "false"],
            },
        },
        "outputs": ["text", "json"],
    },
    "plugin_tool": {
        "category": "wfCat_plugin",
        "label": "wfNode_plugin_tool",
        "description": "wfNode_plugin_tool_desc",
        "config": {
            "plugin_id": {"type": "string", "required": True},
            "tool_name": {"type": "string", "required": True, "depends_on": "plugin_id"},
            # 同一个插件可以接多个连接;留空且只有一个可用连接时自动用它。
            "instance_id": {"advanced": True, "type": "string", "description": "wfNode_plugin_tool_instance_id", "plugin_instances": True, "depends_on": "plugin_id"},
            "input": {"type": "object", "description": "wfNode_plugin_tool_input"},
        },
        "outputs": ["output"],
    },
    "transcribe_asset": {
        "category": "wfCat_ai",
        "label": "wfNode_transcribe_asset",
        "description": "wfNode_transcribe_asset_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "description": "wfNode_transcribe_asset_asset_id"},
            "engine": {
                "type": "string",
                "default": "auto",
                "description": "wfNode_transcribe_asset_engine",
                "options": ["auto", "funasr", "whisperx"],
            },
        },
        "outputs": ["text", "timed_text", "segments", "language", "transcript_id", "duration"],
        "output_types": {"segments": "json", "duration": "number"},
    },
    "export_sequence": {
        "category": "wfCat_asset",
        "label": "wfNode_export_sequence",
        "description": "wfNode_export_sequence_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["asset_id"],
    },
    "asset": {
        "category": "wfCat_asset",
        "label": "wfNode_asset",
        "description": "wfNode_asset_desc",
        "config": {"asset_id": {"type": "template", "required": True}},
        "outputs": ["asset_id", "name", "kind", "duration", "width", "height", "fps"],
        "output_types": {"duration": "number", "width": "number", "height": "number", "fps": "number"},
    },
    "inspect_sequence": {
        "category": "wfCat_asset",
        "label": "wfNode_inspect_sequence",
        "description": "wfNode_inspect_sequence_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["sequence_id", "revision", "tracks", "duration", "video_track_id", "audio_track_id"],
    },
    "timeline_append": {
        "category": "wfCat_asset",
        "label": "wfNode_timeline_append",
        "description": "wfNode_timeline_append_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "description": "wfNode_timeline_append_sequence_id"},
            "asset_id": {"type": "template", "required": True, "description": "wfNode_timeline_append_asset_id"},
            "track_id": {"advanced": True, "type": "template", "description": "wfNode_timeline_append_track_id"},
            "start": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_start"},
            "end": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_end"},
        },
        "outputs": ["clip_id", "timeline_start", "timeline_end", "sequence_id"],
    },
    "timeline_add_track": {
        "category": "wfCat_asset",
        "label": "wfNode_timeline_add_track",
        "description": "wfNode_timeline_add_track_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True},
            "kind": {
                "type": "string",
                "required": True,
                "description": "wfNode_timeline_add_track_kind",
                "options": ["video", "audio", "subtitle"],
            },
        },
        "outputs": ["track_id", "sequence_id"],
    },
    "timeline_clear": {
        "category": "wfCat_asset",
        "label": "wfNode_timeline_clear",
        "description": "wfNode_timeline_clear_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["removed", "sequence_id"],
    },
    "timeline_cut_ranges": {
        "category": "wfCat_asset",
        "label": "wfNode_timeline_cut_ranges",
        "description": "wfNode_timeline_cut_ranges_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True},
            "clip_id": {"type": "template", "required": True, "description": "wfNode_timeline_cut_ranges_clip_id"},
            "ranges": {
                "type": "template",
                "required": True,
                "description": "wfNode_timeline_cut_ranges_ranges",
            },
            "min_confidence": {
                "advanced": True,
                "type": "number",
                "description": "wfNode_timeline_cut_ranges_min_confidence",
            },
            "max_removal_ratio": {
                "advanced": True,
                "type": "number",
                "description": "wfNode_timeline_cut_ranges_max_removal_ratio",
            },
        },
        "outputs": ["removed", "removed_seconds", "ranges", "sequence_id", "revision"],
        "output_types": {"removed": "number", "removed_seconds": "number", "ranges": "json", "revision": "number"},
    },
    "edit_timeline": {
        "category": "wfCat_asset",
        "label": "wfNode_edit_timeline",
        "description": "wfNode_edit_timeline_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True},
            "operations": {
                "type": "template",
                "required": True,
                #: 算子清单**现算**(EDIT_OP_KINDS 是序列域的产地),所以这里存 key + 参数,
                #: 出口按语言把句子组装出来 —— 加一种算子时两种语言同时跟着变。
                "description": "wfNode_edit_timeline_operations",
                "description_params": {"kinds": "、".join(EDIT_OP_KINDS)},
            },
        },
        "outputs": ["applied", "sequence_id", "revision"],
    },
    "ai_generate": {
        "category": "wfCat_ai",
        "label": "wfNode_ai_generate",
        "description": "wfNode_ai_generate_desc",
        "config": {
            "provider": {"type": "string", "required": True},
            "model": {"type": "string", "required": True, "depends_on": "provider"},
            "kind": {"type": "string", "required": True, "description": "wfNode_ai_generate_kind", "options": ["image", "video"]},
            "prompt": {"type": "template", "required": True},
            # 下面三项执行器一直支持,却没在这里声明 —— 于是编辑器渲染不出输入框、AI 助手也不知道
            # 它们存在,工作流里生成不出竖屏视频这类最常见的诉求。声明即接口。
            "negative_prompt": {"advanced": True, "type": "template", "description": "wfNode_ai_generate_negative_prompt"},
            "parameters": {
                "type": "object",
                "description": "wfNode_ai_generate_parameters",
                "description_params": _generation_parameters_help(),
            },
            # **不标 advanced。** 它是图生视频/参考生视频的唯一入口 —— 藏进高级等于把一整类
            # 用法藏起来,而判据的第二条正是"它是不是这个节点在做的事"。
            "source_assets": {
                "type": "template",
                "description": "wfNode_ai_generate_source_assets",
                "description_params": _source_assets_help(),
            },
        },
        "outputs": ["asset_id", "generation_id"],
    },
    "video_to_gif": {
        "category": "wfCat_asset",
        "label": "wfNode_video_to_gif",
        "description": "wfNode_video_to_gif_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "description": "wfNode_video_to_gif_asset_id"},
            "fps": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_fps"},
            "width": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_width"},
            "start": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_start"},
            "duration": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_duration"},
        },
        "outputs": ["asset_id", "source_asset_id"],
    },
    "publish": {
        "category": "wfCat_publish",
        "label": "wfNode_publish",
        "description": "wfNode_publish_desc",
        "config": {
            "account_id": {"type": "string", "required": True, "description": "wfNode_publish_account_id"},
            "asset_id": {"type": "template", "required": True, "description": "wfNode_publish_asset_id"},
            "title": {"type": "template", "description": "wfNode_publish_title"},
            "description": {"type": "template"},
        },
        "outputs": ["result"],
        "output_types": {"result": "json"},
    },
    "condition": {
        "category": "wfCat_flow",
        "label": "wfNode_condition",
        "description": "wfNode_condition_desc",
        "config": {
            "left": {"type": "template", "required": True, "description": "wfNode_condition_left"},
            "op": {
                "type": "string",
                "required": True,
                "description": "wfNode_condition_op",
                "options": ["equals", "not_equals", "contains", "not_contains", "empty", "not_empty", "gt", "lt"],
            },
            "right": {"type": "template", "description": "wfNode_condition_right"},
        },
        "outputs": ["result"],
        "output_types": {"result": "text"},
        "branches": ["true", "false"],
    },
    "http_request": {
        "category": "wfCat_data",
        "label": "wfNode_http_request",
        "description": "wfNode_http_request_desc",
        "config": {
            "method": {"type": "string", "description": "wfNode_http_request_method", "options": ["GET", "POST", "PUT", "DELETE"]},
            "url": {"type": "template", "required": True},
            "headers": {"type": "object"},
            "body": {"type": "template", "description": "wfNode_http_request_body"},
        },
        "outputs": ["status", "text", "json"],
    },
    "code": {
        "category": "wfCat_data",
        "label": "wfNode_code",
        "description": "wfNode_code_desc",
        "config": {
            "code": {"type": "code", "required": True, "description": "wfNode_code_code"},
            "input": {"type": "object"},
        },
        "outputs": ["output"],
    },
    "template": {
        "category": "wfCat_data",
        "label": "wfNode_template",
        "description": "wfNode_template_desc",
        "config": {"template": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "json_extract": {
        "category": "wfCat_data",
        "label": "wfNode_json_extract",
        "description": "wfNode_json_extract_desc",
        "config": {
            "source": {"type": "template", "required": True, "description": "wfNode_json_extract_source"},
            "path": {"type": "template", "description": "wfNode_json_extract_path"},
        },
        "outputs": ["value", "text"],
    },
    "text_transform": {
        "category": "wfCat_data",
        "label": "wfNode_text_transform",
        "description": "wfNode_text_transform_desc",
        "config": {
            "text": {"type": "template", "required": True},
            "op": {
                "type": "string",
                "required": True,
                "description": "wfNode_text_transform_op",
                "options": ["trim", "upper", "lower", "replace", "regex_extract", "length"],
            },
            "find": {"type": "template", "description": "wfNode_text_transform_find"},
            "replace": {"type": "template", "description": "wfNode_text_transform_replace"},
        },
        "outputs": ["text", "length"],
    },
    "delay": {
        "category": "wfCat_flow",
        "label": "wfNode_delay",
        "description": "wfNode_delay_desc",
        "config": {"seconds": {"type": "number", "description": "wfNode_delay_seconds"}},
        "outputs": ["waited"],
    },
    "synthesize_speech": {
        "category": "wfCat_ai",
        "label": "wfNode_synthesize_speech",
        "description": "wfNode_synthesize_speech_desc",
        "config": {
            "voice_id": {"type": "string", "required": True, "description": "wfNode_synthesize_speech_voice_id"},
            "text": {"type": "template", "required": True},
        },
        "outputs": ["asset_id"],
    },
    "notify": {
        "category": "wfCat_publish",
        "label": "wfNode_notify",
        "description": "wfNode_notify_desc",
        "config": {
            "title": {"type": "template", "required": True},
            "body": {"type": "template", "description": "wfNode_notify_body"},
        },
        "outputs": ["sent"],
    },
    "translate": {
        "category": "wfCat_ai",
        "label": "wfNode_translate",
        "description": "wfNode_translate_desc",
        "config": {
            "text": {"type": "template", "required": True},
            "target_lang": {
                "type": "string",
                "required": True,
                "options": ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"],
            },
            "engine": {"type": "string", "description": "wfNode_translate_engine", "options": ["google", "ai"]},
            "profile_id": {"advanced": True, "type": "string", "description": "wfNode_translate_profile_id"},
        },
        "outputs": ["text"],
    },
    "loop_foreach": {
        "category": "wfCat_flow",
        "label": "wfNode_loop_foreach",
        "description": "wfNode_loop_foreach_desc",
        "config": {
            "items": {
                "type": "template",
                "required": True,
                "description": "wfNode_loop_foreach_items",
            },
            "inputs": {
                "type": "object",
                "description": "wfNode_loop_foreach_inputs",
            },
            "body": {"type": "graph", "description": "wfNode_loop_foreach_body"},
            "output": {
                "type": "template",
                "description": "wfNode_loop_foreach_output",
            },
        },
        "outputs": ["results", "count"],
    },
    "loop_while": {
        "category": "wfCat_flow",
        "label": "wfNode_loop_while",
        "description": "wfNode_loop_while_desc",
        "config": {
            "body": {"type": "graph", "description": "wfNode_loop_while_body"},
            "condition": {
                "type": "template",
                "description": "wfNode_loop_while_condition",
            },
            "max_iterations": {"advanced": True, "type": "number", "description": "wfNode_loop_while_max_iterations"},
            "output": {"type": "template", "description": "wfNode_loop_while_output"},
        },
        "outputs": ["results", "count", "iterations"],
    },
    "asset_query": {
        "category": "wfCat_asset",
        "label": "wfNode_asset_query",
        "description": "wfNode_asset_query_desc",
        "config": {
            "kind": {"type": "string", "description": "wfNode_asset_query_kind", "options": ["all", "video", "image", "audio"]},
            "name_contains": {"type": "template", "description": "wfNode_asset_query_name_contains"},
            "tags": {"type": "template", "description": "wfNode_asset_query_tags"},
            "limit": {"advanced": True, "type": "number", "description": "wfNode_asset_query_limit"},
        },
        "outputs": ["assets", "ids", "count"],
    },
    "asset_tag": {
        "category": "wfCat_asset",
        "label": "wfNode_asset_tag",
        "description": "wfNode_asset_tag_desc",
        "config": {
            "asset_ids": {
                "type": "template",
                "required": True,
                "description": "wfNode_asset_tag_asset_ids",
            },
            "tags": {"type": "template", "required": True, "description": "wfNode_asset_tag_tags"},
            "mode": {
                "type": "string",
                "description": "wfNode_asset_tag_mode",
                "options": ["add", "remove", "replace"],
            },
        },
        "outputs": ["updated", "count"],
    },
    "asset_update": {
        "category": "wfCat_asset",
        "label": "wfNode_asset_update",
        "description": "wfNode_asset_update_desc",
        "config": {
            "asset_ids": {"type": "template", "required": True, "description": "wfNode_asset_update_asset_ids"},
            "name": {"type": "template", "description": "wfNode_asset_update_name"},
            "project_id": {"type": "template", "description": "wfNode_asset_update_project_id"},
        },
        "outputs": ["updated", "count"],
    },
    "project_create": {
        "category": "wfCat_asset",
        "label": "wfNode_project_create",
        "description": "wfNode_project_create_desc",
        "config": {
            "name": {"type": "template", "required": True, "description": "wfNode_project_create_name"},
        },
        "outputs": ["project_id", "name"],
    },
    "project_sequence_create": {
        "category": "wfCat_asset",
        "label": "wfNode_project_sequence_create",
        "description": "wfNode_project_sequence_create_desc",
        "config": {
            "name": {"type": "template", "required": True, "description": "wfNode_project_sequence_create_name"},
            "width": {"type": "number", "description": "wfNode_project_sequence_create_width"},
            "height": {"type": "number", "description": "wfNode_project_sequence_create_height"},
            "fps": {"type": "number", "description": "wfNode_project_sequence_create_fps"},
        },
        "outputs": ["project_id", "sequence_id", "video_track_id", "audio_track_id", "name"],
    },
    # 组合/嵌套:把工作流当子流程调用,声明工作流的输出契约。
    "call_workflow": {
        "category": "wfCat_flow",
        "label": "wfNode_call_workflow",
        "description": "wfNode_call_workflow_desc",
        "config": {
            "workflow_id": {"type": "string", "required": True, "description": "wfNode_call_workflow_workflow_id"},
            "inputs": {"type": "object", "description": "wfNode_call_workflow_inputs"},
        },
        "outputs": ["output"],
    },
    "output": {
        "category": "wfCat_flow",
        "label": "wfNode_output",
        "description": "wfNode_output_desc",
        "config": {
            "values": {"type": "object", "description": "wfNode_output_values"},
        },
        "outputs": ["output"],
    },
    "subgraph": {
        "category": "wfCat_flow",
        "label": "wfNode_subgraph",
        "description": "wfNode_subgraph_desc",
        "config": {
            "inputs": {"type": "object", "description": "wfNode_subgraph_inputs"},
            "body": {"type": "graph", "description": "wfNode_subgraph_body"},
            "output": {"type": "template", "description": "wfNode_subgraph_output"},
        },
        "outputs": ["output"],
    },
    # 浏览器自动化(RPA):在隔离浏览器会话里自动化操作网页,与发布登录完全隔离。
    # 典型链路:打开浏览器 → 导航/点击/输入/等待 → 提取 → 关闭。session 输出串起整条链。
    "browser_open": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_open",
        "description": "wfNode_browser_open_desc",
        "config": {
            "url": {"type": "template", "description": "wfNode_browser_open_url"},
            "session_mode": {"type": "string", "options": ["ephemeral", "named", "pool"], "description": "wfNode_browser_open_session_mode"},
            "session_name": {"type": "template", "description": "wfNode_browser_open_session_name"},
            "profile_id": {"type": "string", "description": "wfNode_browser_open_profile_id"},
        },
        "outputs": ["session"],
    },
    "browser_navigate": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_navigate",
        "description": "wfNode_browser_navigate_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_navigate_session"},
            "url": {"type": "template", "required": True, "description": "wfNode_browser_navigate_url"},
        },
        "outputs": ["session"],
    },
    "browser_click": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_click",
        "description": "wfNode_browser_click_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_click_session"},
            "selector": {"type": "template", "description": "wfNode_browser_click_selector"},
            "text": {"type": "template", "description": "wfNode_browser_click_text"},
            "exact": {"advanced": True, "type": "string", "options": ["false", "true"], "description": "wfNode_browser_click_exact"},
        },
        "outputs": ["session"],
    },
    "browser_input": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_input",
        "description": "wfNode_browser_input_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_input_session"},
            "selector": {"type": "template", "required": True, "description": "wfNode_browser_input_selector"},
            "value": {"type": "template", "description": "wfNode_browser_input_value"},
        },
        "outputs": ["session"],
    },
    "browser_upload": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_upload",
        "description": "wfNode_browser_upload_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_upload_session"},
            "selector": {"advanced": True, "type": "template", "description": "wfNode_browser_upload_selector"},
            "asset_id": {"type": "template", "description": "wfNode_browser_upload_asset_id"},
            "file_path": {"type": "template", "description": "wfNode_browser_upload_file_path"},
            "timeout_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_upload_timeout_ms"},
        },
        "outputs": ["session"],
    },
    "browser_extract": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_extract",
        "description": "wfNode_browser_extract_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_extract_session"},
            "selector": {"type": "template", "required": True, "description": "wfNode_browser_extract_selector"},
            "attribute": {"advanced": True, "type": "template", "description": "wfNode_browser_extract_attribute"},
            "all": {"advanced": True, "type": "string", "options": ["false", "true"], "description": "wfNode_browser_extract_all"},
        },
        "outputs": ["session", "value"],
    },
    "browser_wait": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_wait",
        "description": "wfNode_browser_wait_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_wait_session"},
            "selector": {"type": "template", "description": "wfNode_browser_wait_selector"},
            "gone": {"advanced": True, "type": "string", "options": ["false", "true"], "description": "wfNode_browser_wait_gone"},
            "url_contains": {"advanced": True, "type": "template", "description": "wfNode_browser_wait_url_contains"},
            "text": {"advanced": True, "type": "template", "description": "wfNode_browser_wait_text"},
            "timeout_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_wait_timeout_ms"},
        },
        "outputs": ["session"],
    },
    "browser_scroll": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_scroll",
        "description": "wfNode_browser_scroll_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_scroll_session"},
            "selector": {"type": "template", "description": "wfNode_browser_scroll_selector"},
            "dy": {"advanced": True, "type": "number", "description": "wfNode_browser_scroll_dy"},
        },
        "outputs": ["session"],
    },
    "browser_evaluate": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_evaluate",
        "description": "wfNode_browser_evaluate_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_evaluate_session"},
            "expression": {"type": "code", "required": True, "description": "wfNode_browser_evaluate_expression"},
        },
        "outputs": ["session", "value"],
    },
    "browser_close": {
        "category": "wfCat_browser",
        "label": "wfNode_browser_close",
        "description": "wfNode_browser_close_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_close_session"},
        },
        "outputs": [],
    },
}

VARIABLE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def _plugin_types(db: Session) -> dict[str, dict[str, Any]]:
    """当前可用的插件节点。延迟导入:plugins 域会反过来用到工作流的东西(插件工具执行器),
    顶层互相 import 就成了环。"""
    from app.domain.plugins.nodes import plugin_node_types

    return plugin_node_types(db)


def validate_graph(
    graph: dict[str, Any],
    *,
    require_start: bool = True,
    require_config: bool = True,
    allow_missing_start: bool = False,
    extra_types: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """结构校验:返回错误列表(空表 = 合法)。

    extra_types 是**动态**的节点类型(目前只有插件节点,见 domain/plugins/nodes.py):形状与
    NODE_TYPES 的条目一致,合并进来后校验、必填检查一视同仁。之所以从参数进来而不是在这里
    直接查库:这个函数是纯的,而"装了哪些插件"是调用方那一侧的事实 —— 拿不到 db 的调用方
    (比如子图体校验)照样能用它,只是那次校验里没有插件节点。

    require_config=False 用于**保存**:必填字段缺失属于「还没配完」,不该拦住存盘 —— 否则配合
    实时保存,新加一个带必填项的节点就永远存不下来。缺必填由「就绪检查」提示、由运行时拦截。

    allow_missing_start=True 同样用于**保存**:用户可以把画布清空或删除开始节点做草稿;
    运行时仍然 require_start=True 且 allow_missing_start=False,没有开始节点就不能运行。

    require_start=False 用于循环体子图:子图没有 start 节点(执行时由循环上下文喂入
    {{loop.item}}),无入边的节点即为入口;若子图里出现 start 则报错。
    """
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph 必须包含 nodes 与 edges 两个数组"]
    # Only the CONTAINERS were type-checked. Their elements were assumed to be dicts, so
    # {"nodes": ["oops"]} reached .get() and raised AttributeError straight past the
    # WorkflowDomainError handler — a 500 for what is plainly a bad request. This has to come
    # before the first .get() below, not after.
    if any(not isinstance(node, dict) for node in nodes) or any(not isinstance(e, dict) for e in edges):
        return ["节点与连线必须是对象"]

    # 数据边(kind="data")把上游输出绑到目标输入 → 该输入即便字面量为空也算已满足。
    data_bound: set[tuple[str, str]] = {
        (str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in edges
        if str(edge.get("kind", "")) == "data" and edge.get("target_input")
    }

    known_types = {**NODE_TYPES, **(extra_types or {})}

    def _unknown_type_error(node_type: str, node_id: str) -> str:
        # 插件节点在别人机器上会缺:说清楚是"缺哪个插件",而不是一句让人无从下手的"未知类型"。
        from app.domain.plugins.nodes import parse_node_type

        parsed = parse_node_type(node_type)
        if parsed:
            return f"节点 {node_id} 来自插件「{parsed[0]}」的工具 {parsed[1]},该插件未安装或未启用"
        return f"未知节点类型: {node_type} ({node_id})"

    seen_ids: set[str] = set()
    start_count = 0
    for node in nodes:
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        if not node_id:
            errors.append("存在缺少 id 的节点")
            continue
        if node_id in seen_ids:
            errors.append(f"节点 id 重复: {node_id}")
        seen_ids.add(node_id)
        if node_type not in known_types:
            errors.append(_unknown_type_error(node_type, node_id))
            continue
        if node_type == "start":
            start_count += 1
        if require_config:
            for key, spec in known_types[node_type]["config"].items():
                if isinstance(spec, dict) and spec.get("required"):
                    value = (node.get("config") or {}).get(key)
                    if value in (None, "") and (node_id, key) not in data_bound:
                        errors.append(f"节点 {node_id} 缺少必填配置 {key}")
    if require_start:
        if start_count > 1 or (start_count == 0 and not allow_missing_start):
            errors.append(f"工作流必须恰好包含 1 个开始节点(当前 {start_count} 个)")
    elif start_count > 0:
        errors.append("循环体子图不能包含开始节点")

    node_types = {str(node.get("id", "")): str(node.get("type", "")) for node in nodes}
    adjacency: dict[str, list[str]] = {}
    indegree: dict[str, int] = {node_id: 0 for node_id in seen_ids}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in seen_ids or target not in seen_ids:
            errors.append(f"连线引用了不存在的节点: {source} → {target}")
            continue
        handle = edge.get("source_handle")
        if node_types.get(source) == "condition" and handle not in (None, "true", "false"):
            errors.append(f"条件节点的分支端点必须是 true/false: {source}")
        adjacency.setdefault(source, []).append(target)
        indegree[target] = indegree.get(target, 0) + 1

    # Kahn 拓扑排序检环
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    degrees = dict(indegree)
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency.get(current, []):
            degrees[nxt] -= 1
            if degrees[nxt] == 0:
                queue.append(nxt)
    if seen_ids and visited != len(seen_ids):
        errors.append("工作流包含环路,必须是有向无环图")
    return errors


# 内嵌子图类节点:body/output/condition 属于**内层**作用域(见 binding.interpolate_node_config
# 保留原文的理由),既是插值时机的依据,也是校验时不下钻的依据。binding.py 从这里取,单一真源。
NESTED_BODY_TYPES = frozenset({"loop_foreach", "loop_while", "subgraph"})
NESTED_BODY_RAW_KEYS = ("body", "output", "condition")


def validate_body_graph(body: dict[str, Any], *, scope: str = "loop") -> list[str]:
    """内嵌子图(循环体 / subgraph)校验:必须非空、无 start 节点、其余同 validate_graph;
    再查引用是否越出作用域。scope 是执行时播种的作用域名——循环体用 "loop"、subgraph 用 "input"。"""
    label = "循环体" if scope == "loop" else "子图"
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return [f"{label}不能为空,至少要有一个节点"]
    errors = validate_graph(body, require_start=False)
    errors.extend(_unresolvable_body_refs(nodes, scope))
    return errors


def _unresolvable_body_refs(nodes: list[Any], scope: str) -> list[str]:
    """Reject a body template that references anything outside its own scope.

    A body context is seeded with the scope var (`loop` for loops, `input` for subgraph) and the
    body's own nodes — nothing else. A body node referencing an outer node like {{start.prefix}}
    therefore interpolated to the empty string: no error, no warning, just silently missing text in
    whatever the body produced. That is the worst failure mode available, so name it at validation
    time instead.

    (Making the body actually see the outer scope is not a matter of passing more context: body,
    output and condition are deliberately left un-interpolated at the outer scope so that
    {{loop.item}} / {{input.x}} survive to be resolved when the body runs. Resolving outer
    references there too means a second, guarded pass — a real change, not a tweak.)

    Nested bodies are NOT descended into: a nested loop/subgraph node's own body/output/condition
    belong to *its* inner scope and are validated when it runs. Scanning them here would misreport
    the inner body's node names as out-of-scope references. Its `inputs`/`items` (outer-facing) are
    still scanned, since those resolve in *this* scope.
    """
    # 循环体除 loop.item/index 外还能读取显式传入的 input.*。这不是偷看外层作用域:
    # 外层值必须逐项写进循环节点的 inputs,因此依赖在画布上仍然清楚可见。
    roots = {scope, "input"} if scope == "loop" else {scope}
    known = roots | {str(node.get("id", "")) for node in nodes if isinstance(node, dict)}
    unknown: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = dict(node.get("config") or {})
        if node.get("type") in NESTED_BODY_TYPES:
            for key in NESTED_BODY_RAW_KEYS:
                config.pop(key, None)
        for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False)):
            root = match.group(1).strip().split(".")[0]
            if root and root not in known:
                unknown.add(root)
    if not unknown:
        return []
    if scope == "loop":
        return [
            f"循环体引用了循环外的节点:{', '.join(sorted(unknown))};"
            "循环体只能引用 loop、input 与体内节点"
        ]
    return [f"子图引用了作用域外的节点:{', '.join(sorted(unknown))};子图只能引用 input 与体内节点"]


#: 后果**落在这个应用之外**的节点:发出去的帖子、别人服务器上的改动、本机跑过的代码、
#: 用真实浏览器点下去的按钮。它们决定确认卡的权限档 —— `edit` 撤得回、`ai-cost` 最坏是花钱,
#: 这一档撤不回来。
#:
#: 浏览器节点整组算在内:一张图只要驱动浏览器,它做了什么就不再由这张图本身说了算。
#: `plugin_tool` 算在内:插件工具可以是写类的(manifest 里的 read_only 是自报的,不是判据)。
#: `call_workflow` 算在内是**保守**:它按 id 引用另一张图,扫描器跟不过去(跟过去要查库递归),
#: 跟不过去就不能假装那张图是干净的。
EXTERNAL_NODE_TYPES = frozenset(
    {
        "code",
        "http_request",
        "publish",
        "plugin_tool",
        "call_workflow",
        "browser_open",
        "browser_navigate",
        "browser_click",
        "browser_input",
        "browser_upload",
        "browser_extract",
        "browser_wait",
        "browser_scroll",
        "browser_evaluate",
        "browser_close",
    }
)

#: 明确判定为「后果留在这个应用内」的节点。**与 EXTERNAL_NODE_TYPES 合起来必须覆盖 NODE_TYPES
#: 全部** —— 由测试钉住。新增一个节点类型时作者必须归类,而不是让它默认落进"安全"那一边:
#: 漏掉的那一个恰恰会是没人想过后果的那一个。
#: 容器节点(loop/subgraph)本身是内部的 —— 危险的是它们的体,而体会被递归扫到。
INTERNAL_NODE_TYPES = frozenset(
    {
        "start",
        "llm",
        "transcribe_asset",
        "export_sequence",
        # 编排/检视时间线改的是**本地序列**,后果留在这个应用里;而且每一步都记进
        # sequence_operations,用户撤得回来。
        "asset",
        "inspect_sequence",
        "edit_timeline",
        "timeline_append",
        "timeline_add_track",
        "timeline_clear",
        "timeline_cut_ranges",
        "ai_generate",
        "video_to_gif",
        "condition",
        "template",
        "json_extract",
        "text_transform",
        "delay",
        "synthesize_speech",
        "notify",
        "translate",
        "loop_foreach",
        "loop_while",
        "asset_query",
        "asset_tag",
        "asset_update",
        "project_create",
        "project_sequence_create",
        "output",
        "subgraph",
    }
)

_MAX_GRAPH_SCAN_DEPTH = 16


def _nodes_of_types(graph: Any, types: frozenset[str], *, _depth: int = 0) -> set[str]:
    """递归找出图里用到的、属于 `types` 的节点类型(含 loop/subgraph 的内嵌体)。

    **必须递归**:内嵌体是 config["body"] 里的一整张图,只查顶层的话,把节点框选「折叠为子图」
    就能整个绕过。深度上限只是防御畸形/自引用输入——真实嵌套受 MAX_NEST_DEPTH 约束,远小于它。

    两个扫描(特权 / 外部)共用这一段:递归本身是易错的部分,写两遍就会有一遍将来漏掉子图。
    """
    if _depth > _MAX_GRAPH_SCAN_DEPTH or not isinstance(graph, dict):
        return set()
    found: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        if ntype in types:
            found.add(ntype)
        if ntype in NESTED_BODY_TYPES:
            found |= _nodes_of_types((node.get("config") or {}).get("body"), types, _depth=_depth + 1)
    return found


def external_nodes_in_graph(graph: Any) -> set[str]:
    """图里用到的**后果在应用之外**的节点 —— 决定确认卡的权限档(见 domain/agent/confirmations)。"""
    return _nodes_of_types(graph, EXTERNAL_NODE_TYPES)


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """稳定拓扑序(按 nodes 数组原顺序打破平局)。假定 graph 已通过校验。"""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    indegree = {str(n["id"]): 0 for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
        indegree[str(edge["target"])] += 1
    order: list[dict[str, Any]] = []
    by_id = {str(n["id"]): n for n in nodes}
    ready = [str(n["id"]) for n in nodes if indegree[str(n["id"])] == 0]
    while ready:
        current = ready.pop(0)
        order.append(by_id[current])
        for nxt in adjacency.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order


def interpolate(value: Any, context: dict[str, dict[str, Any]]) -> Any:
    """把字符串里的 {{node.key}} 换成上下文值;整串引用时保留原类型。"""
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    if not isinstance(value, str):
        return value

    def lookup(ref: str) -> Any:
        # Walk a dotted path: {{node.key}}, and nested {{loop.item.name}} / {{q.assets.0.id}}.
        parts = ref.split(".")
        if parts[0] not in context:
            # A miss must read as empty, not as the {} sentinel used to walk the path. Returning
            # the dict meant a typo'd `condition` made _truthy({}) false — so a while loop ran
            # exactly once and looked deliberate — while a typo'd `left` with op `not_empty`
            # evaluated TRUE, because str({}) is non-empty. The branch silently inverted.
            return ""
        current: Any = context[parts[0]]
        for part in parts[1:]:
            if isinstance(current, dict):
                current = current.get(part, "")
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return ""
            else:
                return ""
        return current

    whole = VARIABLE_RE.fullmatch(value.strip())
    if whole:
        return lookup(whole.group(1))
    return VARIABLE_RE.sub(lambda m: str(lookup(m.group(1))), value)


def list_workflows(db: Session, workspace_id: str) -> list[Workflow]:
    return list(
        db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(Workflow.updated_at.desc()))
    )


def create_workflow(
    db: Session,
    *,
    workspace_id: str,
    name: str,
    description: str = "",
    graph: dict[str, Any] | None = None,
    source: str = "create",
    created_by: str | None = None,
    revision_note: str = "",
) -> Workflow:
    graph = graph if graph is not None else default_graph()
    from app.domain.workflows.normalization import canonicalize_data_bindings

    extra_types = _plugin_types(db)
    graph = canonicalize_data_bindings(graph, node_types={**NODE_TYPES, **extra_types})
    # 保存放行「还没配完」:必填缺失交给就绪检查与运行时,否则新节点存不下来。
    errors = validate_graph(graph, require_config=False, allow_missing_start=True, extra_types=extra_types)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    workflow = Workflow(workspace_id=workspace_id, name=name, description=description, graph=graph)
    db.add(workflow)
    from app.domain.workflows.revisions import create_initial_revision

    create_initial_revision(
        db,
        workflow,
        source=source,
        created_by=created_by,
        note=revision_note,
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def update_workflow(
    db: Session,
    workflow: Workflow,
    changes: dict[str, Any],
    *,
    source: str = "edit",
    created_by: str | None = None,
    revision_note: str = "",
) -> Workflow:
    graph = changes.get("graph")
    if "graph" in changes and changes["graph"] is not None:
        from app.domain.workflows.normalization import canonicalize_data_bindings

        extra_types = _plugin_types(db)
        graph = canonicalize_data_bindings(graph, node_types={**NODE_TYPES, **extra_types})
        errors = validate_graph(graph, require_config=False, allow_missing_start=True, extra_types=extra_types)
        if errors:
            raise WorkflowDomainError("；".join(errors))
    if changes.get("name"):
        workflow.name = changes["name"]
    if changes.get("description") is not None:
        workflow.description = changes["description"]
    if graph is not None:
        from app.domain.workflows.revisions import commit_graph_revision

        commit_graph_revision(
            db,
            workflow,
            graph,
            source=source,
            created_by=created_by,
            note=revision_note,
        )
    db.commit()
    db.refresh(workflow)
    return workflow


def default_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 80, "y": 160}, "config": {"params": {}}}
        ],
        "edges": [],
    }
