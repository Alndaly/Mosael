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

from app.ai.providers.contracts.denoise import DEFAULT_STRENGTH, STRENGTHS
from app.ai.providers.registry import DENOISE_ADAPTERS, SEPARATION_ADAPTERS
from app.domain.generation.catalog import BUILTIN_MODELS, SOURCE_GROUPS, SOURCE_ROLE_LABELS
from app.domain.scenes import REFERENCE_RENDERS
from app.domain.sequences.operations import EDIT_OP_KINDS

import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.workflows.field_activation import config_field_active


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

    **第一个参数可以是 i18n 的 key,也可以是一句现成的话** —— 和任务消息那条路同构
    (见 domain/jobs.say):认得出 key 就按读的人的语言翻,认不出就当字面量原样用。
    失败原因会落库(Job.error_key / error_params),所以翻译发生在**读的时候**,而不是写的时候:
    写入时翻会把语言冻死在那一刻,用户切成英文后历史任务里的失败原因仍是中文。

    报错文本里的数据走 `params`,不要拼进句子 —— 拼进去那句话就只有一种语言了。
    """

    def __init__(self, message: str, *, params: dict[str, Any] | None = None,
                 details: dict[str, Any] | None = None) -> None:
        from app.core.i18n import DEFAULT_LOCALE, is_message_key, render_message, stored_param

        #: **只有认得出的才是 key。** 此前无条件记成 key,于是十几处 `WorkflowDomainError(str(exc))`
        #: 把第三方报错原文当 key 落了库(见 core/i18n.is_message_key)。
        self.key = message if is_message_key(message) else ""
        self.message = message
        #: 参数里的文案片段(如 field_name 给的字段名)原样留着,渲染时按读的人的语言翻。
        self.params = {k: stored_param(v) for k, v in (params or {}).items()}
        #: args 里放的是**缺省语言**那一句:pickle、repr 之类不经过 __str__ 的地方读它。
        super().__init__(render_message(message, DEFAULT_LOCALE, self.params))
        self.details = details or {}

    def __str__(self) -> str:
        """按**当时**的语言说 —— 和 LocalizedError 一样取 ContextVar。

        执行线程里没有请求语言,取到的就是缺省语言(日志、落库的 `error` 都读它,和此前一样);
        而编辑器里同步报的那些(图操作、导入文件)是在请求里抛的,路由拿 str(exc)
        当 detail,此前永远给缺省语言 —— 英文界面里弹出一句中文。
        """
        from app.core.i18n import get_current_locale, render_message

        return render_message(self.message, get_current_locale(), self.params)

    @classmethod
    def from_error(cls, exc: BaseException, *, details: dict[str, Any] | None = None) -> WorkflowDomainError:
        """把别的领域的错误转述成工作流错误,**带着它的 key 和参数**。

        此前各执行器写的是 `WorkflowDomainError(str(exc))`:那一刻就把话翻成了字,key 丢了,
        落库的失败原因从此只有写下它那一刻的语言(执行线程里就是缺省语言)。别的领域的错误
        改成 LocalizedError 之后,这条路是它们的 key 走进任务失败原因的唯一通道。
        认不出 key 的(第三方库的原话)照旧当字面量。
        """
        from app.core.i18n import is_message_key

        # 别的领域带着的失败现场(如「这一版要主人认可」的 attest,见 domain/authority)跟着走。
        if details is None and isinstance(getattr(exc, "details", None), dict):
            details = dict(exc.details)  # type: ignore[attr-defined]
        key = str(getattr(exc, "key", "") or "")
        if is_message_key(key):
            return cls(key, params=dict(getattr(exc, "params", None) or {}), details=details)
        return cls(str(exc), details=details)


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
#: (AI / 音频 / 素材 / 数据),然后是把结果送出去(发布),最后才是两类"需要额外准备"的能力 ——
#: 浏览器要登录态,插件要先装。列表顺序即面板顺序,前端不再排第二次。
#:
#: **「音频」单独一组**:转写、语音合成、字幕配音、人声/背景音分离是同一条流水线上的几步,
#: 此前前三个在「AI」、分离在「素材」(和十几个时间线操作挤在一起)—— 按"它是不是 AI"分组,
#: 用户按"我要处理声音"去找时找不到。
#: 分组名也存 key —— 它出现在节点面板的每一栏标题上,写死的话英文界面下那几栏还是中文。
NODE_CATEGORIES: tuple[str, ...] = (
    "wfCat_flow",
    "wfCat_ai",
    "wfCat_audio",
    "wfCat_asset",
    #: 3D 白模:搭场景、渲参考。跟在「素材」后面 —— 它产出的就是给生成用的参考素材。
    "wfCat_3d",
    "wfCat_knowledge",
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
    """这个字段用哪种编辑器:map(一行一对)/ json(原始 JSON)/ 某个专用控件 / 空(按类型走)。

    **声明写了就听声明,不管是什么类型** —— 有些字段的值形状很普通(一串逗号分隔的 id),
    但挑它的过程不普通(要列出这个工作区里的 3D 模型、能多选)。此前这里只认 object,于是
    这种字段只能靠前端按「节点类型 + 字段名」认出来,而那正是这份注册表要消灭的那种手抄表。
    """
    explicit = str(spec.get("editor") or "").strip()
    if explicit:
        return explicit
    if str(spec.get("type") or "") != "object":
        return ""
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
    "attribute": "wfField_attribute",
    "body": "wfField_body",
    "citation_url": "wfField_citation_url",
    "clip_id": "wfField_clip_id",
    "clip_ids": "wfField_clip_ids",
    "code": "wfField_code",
    "condition": "wfField_condition",
    "description": "wfField_description",
    "original_audio": "wfField_original_audio",
    "duration": "wfField_duration",
    "dy": "wfField_dy",
    "end": "wfField_end",
    "engine": "wfField_engine",
    "concurrency": "wfField_concurrency",
    "start_field": "wfField_start_field",
    "end_field": "wfField_end_field",
    "text_field": "wfField_text_field",
    "allow_empty": "wfField_allow_empty",
    "at": "wfField_at",
    "max_duration": "wfField_max_duration",
    "strength": "wfField_strength",
    "exact": "wfField_exact",
    "expression": "wfField_expression",
    "file_path": "wfField_file_path",
    "find": "wfField_find",
    "fps": "wfField_fps",
    "frequency_penalty": "wfField_frequency_penalty",
    "gone": "wfField_gone",
    "has_more": "wfField_has_more",
    "headers": "wfField_headers",
    "height": "wfField_height",
    "input": "wfField_input",
    "inputs": "wfField_inputs",
    "instance_id": "wfField_instance_id",
    "items": "wfField_items",
    "json_schema": "wfField_json_schema",
    "json_schema_name": "wfField_json_schema_name",
    "json_schema_strict": "wfField_json_schema_strict",
    "keep_original": "wfField_keep_original",
    "kind": "wfField_kind",
    "left": "wfField_left",
    "limit": "wfField_limit",
    "line": "wfField_line",
    "markdown": "wfField_markdown",
    "match_duration": "wfField_match_duration",
    "max_iterations": "wfField_max_iterations",
    "max_removal_ratio": "wfField_max_removal_ratio",
    "max_tokens": "wfField_max_tokens",
    "method": "wfField_method",
    "min_confidence": "wfField_min_confidence",
    "mode": "wfField_mode",
    "model": "wfField_model",
    "name": "wfField_name",
    "name_contains": "wfField_name_contains",
    "negative_prompt": "wfField_negative_prompt",
    "note_id": "wfField_note_id",
    "notes": "wfField_notes",
    "offset": "wfField_offset",
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
    #: 生成节点上随模型一起存的连接身份 —— 和 profile_id 是同一个东西,复用同一份翻译。
    "provider_profile_id": "wfField_profile_id",
    "project_id": "wfField_project_id",
    "prompt": "wfField_prompt",
    "provider": "wfField_provider",
    "query": "wfField_query",
    "ranges": "wfField_ranges",
    "replace": "wfField_replace",
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
    "speed": "wfField_speed",
    "start": "wfField_start",
    "stop": "wfField_stop",
    "system": "wfField_system",
    "tags": "wfField_tags",
    "target_lang": "wfField_target_lang",
    "temperature": "wfField_temperature",
    "template": "wfField_template",
    "text": "wfField_text",
    "texts": "wfField_texts",
    "timeout_ms": "wfField_timeout_ms",
    "title": "wfField_title",
    "tool_name": "wfField_tool_name",
    "top_p": "wfField_top_p",
    "track_id": "wfField_track_id",
    "url": "wfField_url",
    "url_contains": "wfField_url_contains",
    "value": "wfField_value",
    "values": "wfField_values",
    "voice": "wfField_voice",
    "width": "wfField_width",
    "workflow_id": "wfField_workflow_id",
    # 下列主要出现在输出端,也可被同名配置字段复用。
    "applied": "wfField_applied",
    "assets": "wfField_assets",
    "audio_track_id": "wfField_audio_track_id",
    "count": "wfField_count",
    "done": "wfField_done",
    "failed": "wfField_failed",
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
    "layout": "wfField_layout",
    "scene_id": "wfField_scene_id",
    "model_ids": "wfField_model_ids",
    "shot_id": "wfField_shot_id",
    "shot_ids": "wfField_shot_ids",
    "shot_count": "wfField_shot_count",
    "render": "wfField_render",
    "source_group": "wfField_source_group",
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


def field_name(key: str, spec: dict[str, Any] | None = None) -> Any:
    """报错里提到一个配置字段时,填进参数的那个名字。

    和界面上那一格**同一个名字**(config_label),而且以文案片段的形状进参数(见
    core/i18n.fragment):失败原因落库之后,读的时候和外层句子一起按读的人的语言翻。
    当场写成字的话 —— 中文字段名嵌进英文句子,或者英文键名 `max_tokens` 嵌进中文句子。
    """
    from app.core.i18n import fragment

    return fragment(config_label(key, spec or {}))


def available_node_types(db: Session, *, user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """**这台机器上此刻可用的全部节点类型** —— 内置的加上插件的。

    收敛成一个函数,是因为它此前被组装了两次:接口层一次(内置 + 插件 + 翻译 + 排序),
    AI 编排里一次(**只有内置,什么都没有**)。于是同一句"可用节点类型"在两条路上含义不同:

    - 模型不知道插件节点存在 —— 而 `plugin_node_types` 存在的全部意义就是让插件节点
      "和内置节点没有区别";
    - 更糟的是校验:AI 编排调 `validate_graph` 时不带 `extra_types`,而提示词又要求模型
      "保留用户没让你改的部分",于是图里原样留着的那个插件节点被判成未知类型,报出
      **「该插件未安装或未启用」** —— 插件明明装着、开着,画布上跑得好好的,而用户会照着
      这句话去插件页找问题。

    `db` 是必需的:装了什么插件是**用户机器上的事实**,不是这份代码的常量(见 plugins/nodes)。
    """
    from app.domain.plugins.nodes import plugin_node_types

    return {**NODE_TYPES, **plugin_node_types(db, user_id)}


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
        "external": False,
        "category": "wfCat_flow",
        "label": "wfNode_start",
        "description": "wfNode_start_desc",
        "config": {"params": {"type": "object", "description": "wfNode_start_params"}},
        "outputs": ["*params"],
    },
    "llm": {
        "external": False,
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
            "profile_id": {"type": "string", "description": "wfNode_llm_profile_id", "options_from": "chat_connections"},
            "model": {"type": "string", "description": "wfNode_llm_model", "depends_on": "profile_id", "options_from": "chat_models", "allow_custom": True},
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
        #: `response_format_used`:这一轮**实际**跑在哪一档(json_schema / json_object / text)。
        #: 配置上写着 json_schema 不等于它生效了 —— 端点可能已查证不支持、可能当场 400、
        #: 也可能在这一档下返回空正文,三种情况都会降级。降级本身是对的,坏的是它一声不吭:
        #: 那时模型只是"看过一份贴在提示词里的 Schema",没有任何东西强制它遵守。
        "outputs": ["text", "json", "response_format_used"],
        "output_labels": {"response_format_used": "wfOut_response_format_used"},
    },
    "plugin_tool": {
        "external": True,
        "category": "wfCat_plugin",
        "label": "wfNode_plugin_tool",
        "description": "wfNode_plugin_tool_desc",
        "config": {
            "plugin_id": {"type": "string", "required": True, "options_from": "plugin_packages"},
            "tool_name": {"type": "string", "required": True, "depends_on": "plugin_id", "options_from": "plugin_tools"},
            # 同一个插件可以接多个连接;留空且只有一个可用连接时自动用它。
            "instance_id": {"advanced": True, "type": "string", "description": "wfNode_plugin_tool_instance_id", "plugin_instances": True, "depends_on": "plugin_id"},
            "input": {"type": "object", "description": "wfNode_plugin_tool_input"},
        },
        "outputs": ["output"],
    },
    "transcribe_asset": {
        "external": False,
        "category": "wfCat_audio",
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
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_export_sequence",
        "description": "wfNode_export_sequence_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["asset_id"],
    },
    "note_search": {
        "external": False,
        "category": "wfCat_knowledge", "label": "wfNode_note_search", "description": "wfNode_note_search_desc",
        "config": {"query": {"type": "template"}, "limit": {"type": "number", "default": 10},
                   "offset": {"type": "number", "default": 0, "advanced": True}},
        "outputs": ["notes", "ids", "count", "has_more", "text"],
        "output_types": {"notes": "json", "ids": "json", "count": "number", "has_more": "json", "text": "text"},
    },
    "note_read": {
        "external": False,
        "category": "wfCat_knowledge", "label": "wfNode_note_read", "description": "wfNode_note_read_desc",
        # 两个字段不分档(见 tests/test_advanced_split_is_sane.py):藏起唯一的可选项,
        # 省下的空间抵不上多出来的那一次点击。
        #: note_id 用笔记选择器挑(也能填上游的 `{{…}}`)—— 控件由声明点名,见 config_editor。
        "config": {"note_id": {"type": "template", "required": True, "editor": "note_ref"},
                   "revision": {"type": "number"}},
        "outputs": ["note_id", "title", "text", "markdown", "tags", "revision", "citation_url"],
        "output_types": {"note_id": "text", "text": "text", "markdown": "text", "tags": "json", "revision": "number"},
    },
    "note_create": {
        "external": False,
        "category": "wfCat_knowledge", "label": "wfNode_note_create", "description": "wfNode_note_create_desc",
        "config": {"title": {"type": "template", "required": True},
                   "markdown": {"type": "template", "required": True}, "tags": {"type": "template", "advanced": True}},
        "outputs": ["note_id", "title", "revision", "citation_url"],
        "output_types": {"note_id": "text", "revision": "number"},
    },
    "asset": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_asset",
        "description": "wfNode_asset_desc",
        "config": {"asset_id": {"type": "template", "required": True}},
        "outputs": ["asset_id", "name", "kind", "duration", "width", "height", "fps"],
        "output_types": {"duration": "number", "width": "number", "height": "number", "fps": "number"},
    },
    "inspect_sequence": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_inspect_sequence",
        "description": "wfNode_inspect_sequence_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["sequence_id", "revision", "tracks", "duration", "video_track_id", "audio_track_id"],
    },
    "timeline_append": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_timeline_append",
        "description": "wfNode_timeline_append_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "description": "wfNode_timeline_append_sequence_id"},
            "asset_id": {"type": "template", "required": True, "description": "wfNode_timeline_append_asset_id"},
            "track_id": {"advanced": True, "type": "template", "description": "wfNode_timeline_append_track_id"},
            "start": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_start"},
            "end": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_end"},
            "at": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_at"},
            "max_duration": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_max_duration"},
        },
        "outputs": ["clip_id", "timeline_start", "timeline_end", "sequence_id"],
    },
    "timeline_add_track": {
        "external": False,
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
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_timeline_clear",
        "description": "wfNode_timeline_clear_desc",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["removed", "sequence_id"],
    },
    "timeline_cut_ranges": {
        "external": False,
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
        "external": False,
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
        "external": False,
        "category": "wfCat_ai",
        "label": "wfNode_ai_generate",
        "description": "wfNode_ai_generate_desc",
        "config": {
            # 连接身份随模型一起存；同一 vendor/model 可以存在于多条端点，二元组不再唯一。
            "provider_profile_id": {"type": "string"},
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
            #: 值是**行的列表**,每行 `素材:角色`;某一行可以是一整串引用(一组这样的行)。
            "source_assets": {
                "type": "template",
                "lines": True,
                "description": "wfNode_ai_generate_source_assets",
                "description_params": _source_assets_help(),
            },
            #: 首尾帧组和参考素材组互斥时用哪一组(见 generation/catalog.SOURCE_GROUPS)。
            #: 允许手填:整片流程里是逐镜决定的,值来自上游(`{{…}}`)。
            "source_group": {
                "advanced": True, "type": "string", "default": "all", "options": list(SOURCE_GROUPS),
                "allow_custom": True, "description": "wfNode_ai_generate_source_group",
            },
        },
        #: asset_id 是**封面**(下游多数节点只接一份),asset_ids 是这次出的全部 ——
        #: 图像接口的 n 能一次出好几张,不声明的话下游连不到它们(执行体一直在返回)。
        "outputs": ["asset_id", "asset_ids", "generation_id"],
    },
    "video_to_gif": {
        "external": False,
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
        "external": True,
        "category": "wfCat_publish",
        "label": "wfNode_publish",
        "description": "wfNode_publish_desc",
        "config": {
            "account_id": {"type": "string", "required": True, "description": "wfNode_publish_account_id", "options_from": "publish_accounts"},
            "asset_id": {"type": "template", "required": True, "description": "wfNode_publish_asset_id"},
            "title": {"type": "template", "description": "wfNode_publish_title"},
            "description": {"type": "template"},
        },
        # post_id / post_url:发出去的那条作品在平台上的 ID 与链接(见 domain/publish/post.py),
        # 下游拿它去查这条作品的数据。平台接口没读到时是空串。
        "outputs": ["post_id", "post_url", "result"],
        "output_types": {"result": "json"},
        "output_labels": {"post_id": "wfOut_post_id", "post_url": "wfOut_post_url"},
    },
    "condition": {
        "external": False,
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
        "external": True,
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
        "external": True,
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
        "external": False,
        "category": "wfCat_data",
        "label": "wfNode_template",
        "description": "wfNode_template_desc",
        "config": {"template": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "json_extract": {
        "external": False,
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
        "external": False,
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
        "external": False,
        "category": "wfCat_flow",
        "label": "wfNode_delay",
        "description": "wfNode_delay_desc",
        "config": {"seconds": {"type": "number", "description": "wfNode_delay_seconds"}},
        "outputs": ["waited"],
    },
    "synthesize_speech": {
        "external": False,
        "category": "wfCat_audio",
        "label": "wfNode_synthesize_speech",
        "description": "wfNode_synthesize_speech_desc",
        # **一对「引擎 + 音色」,音色只有一格。** 引擎先说嗓子从哪来(克隆 / 某个引擎),音色
        # 那一格的清单跟着引擎变:克隆时是工作区音色库,选了引擎就是那个引擎的目录。
        # 此前存成两个键(voice_id / engine_voice)再由前端按引擎只显示其一 —— 两个键的顺序
        # 一前一后,于是换引擎时音色那一格上下跳,看起来就是两个音色框;而"显示哪一个"
        # "顺手填资源号"都是前端按节点类型写死的特例。现在清单来源由 options_from 声明,
        # 资源号由执行体自己查,前端不认识这个节点。
        "config": {
            "text": {"type": "template", "required": True},
            "engine": {
                "type": "string",
                # 留空 = 克隆,和执行体一致。
                "default": "clone",
                "options_from": "speech_engines",
                "description": "wfNode_speech_engine",
            },
            # 换引擎就换了一整套音色 id —— depends_on 让前端清掉旧值,也把引擎的值带给选项来源。
            "voice": {
                "type": "string",
                "required": True,
                "depends_on": "engine",
                "options_from": "speech_voices",
                "description": "wfNode_speech_voice",
            },
            "speed": {"advanced": True, "type": "number", "description": "wfNode_synthesize_speech_speed"},
        },
        "outputs": ["asset_id"],
    },
    "notify": {
        "external": False,
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
        "external": False,
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
            "engine": {"type": "string", "description": "wfNode_translate_engine", "options": ["google", "ai"], "default": "google"},
            "profile_id": {"type": "string", "description": "wfNode_translate_profile_id", "depends_on": "engine", "options_from": "chat_connections", "active_when": {"engine": "ai"}},
            # 一条连接上常常挂着好几个模型 —— 「用哪条连接」和「用哪个模型」是两个问题。
            # 留空按这条连接的 chat 能力解析(和 llm 节点同一条路)。
            "model": {"type": "string", "description": "wfNode_translate_model", "depends_on": "profile_id", "options_from": "chat_models", "allow_custom": True, "active_when": {"engine": "ai"}},
        },
        "outputs": ["text"],
    },
    #: 整轨一次翻完。逐句循环也能得到同样的结果,但那是 N 次**串行**节点调用,每次一个
    #: 新连接;而免费端点按 IP 限流,串起来正好踩在它的节流上。这里走 translate_many:
    #: 8 路并发 + 共用一条连接,顺带共用重试。
    "translate_lines": {
        "external": False,
        "category": "wfCat_ai",
        "label": "wfNode_translate_lines",
        "description": "wfNode_translate_lines_desc",
        "config": {
            "texts": {"type": "template", "required": True, "description": "wfNode_translate_lines_texts"},
            "target_lang": {
                "type": "string",
                "required": True,
                "options": ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"],
            },
            "engine": {"type": "string", "description": "wfNode_translate_engine", "options": ["google", "ai"], "default": "google"},
            # 选了 ai 之后「用哪条连接」立刻变成要紧事,所以它不在高级里。
            # depends_on:换引擎就换了这一格的意义(google 下它没用),声明出来界面才会跟着变。
            "profile_id": {"type": "string", "description": "wfNode_translate_profile_id", "depends_on": "engine", "options_from": "chat_connections", "active_when": {"engine": "ai"}},
            # 一条连接上常常挂着好几个模型 —— 「用哪条连接」和「用哪个模型」是两个问题。
            # 留空按这条连接的 chat 能力解析(和 llm 节点同一条路)。
            "model": {"type": "string", "description": "wfNode_translate_model", "depends_on": "profile_id", "options_from": "chat_models", "allow_custom": True, "active_when": {"engine": "ai"}},
        },
        "outputs": ["texts", "count"],
        "output_types": {"texts": "json", "count": "number"},
    },
    #: 人声/背景音分离(ADR-0016)。**产出两份新素材,原素材一个字节不动。**
    #: 3D 白模(见 executors/scenes.py 与 domain/scene_render)。
    #: 交给布景师的**道具清单**:这个工作区里(通常是在 Blender 里建好再收进来的)哪些模型
    #: 可以摆进布景,各自多大。没有它的话,设计布景的那个 LLM 不可能凭空写出一串模型 id ——
    #: 于是自动流程里的布景永远只能是基本体拼的。
    "scene_props": {
        "external": False,
        "category": "wfCat_3d",
        "label": "wfNode_scene_props",
        "description": "wfNode_scene_props_desc",
        "config": {
            #: 值是一串逗号分隔的模型 id。挑的过程要列出这个工作区的模型、能多选,
            #: 所以给它一个专用控件(见 config_editor 的说明)。
            "model_ids": {"type": "template", "editor": "scene_models",
                          "description": "wfNode_scene_props_model_ids"},
        },
        "outputs": ["catalog", "model_ids", "count"],
        "output_labels": {
            "catalog": "wfOut_props_catalog",
            "model_ids": "wfOut_props_model_ids",
            "count": "wfOut_props_count",
        },
        "output_types": {"model_ids": "json", "count": "number"},
    },
    "scene_create": {
        "external": False,
        "category": "wfCat_3d",
        "label": "wfNode_scene_create",
        "description": "wfNode_scene_create_desc",
        "config": {
            "name": {"type": "template", "description": "wfNode_scene_create_name"},
            #: 布景就是 SceneContent 的形状 —— 物体、机位轨迹、镜头、打光。通常接一个 LLM 的结构化输出。
            "layout": {"type": "template", "required": True, "data_type": "json", "description": "wfNode_scene_create_layout"},
        },
        "outputs": ["scene_id", "shot_ids", "shot_count"],
        "output_types": {"shot_ids": "json", "shot_count": "number"},
    },
    "scene_render": {
        "external": False,
        "category": "wfCat_3d",
        "label": "wfNode_scene_render",
        "description": "wfNode_scene_render_desc",
        "config": {
            "scene_id": {"type": "template", "required": True, "description": "wfNode_scene_render_scene_id"},
            "shot_id": {"type": "template", "required": True, "description": "wfNode_scene_render_shot_id"},
            #: 允许手填:整片流程里"这一镜要不要运镜视频"是逐镜决定的,值来自上游(`{{…}}`)。
            "render": {
                "type": "string", "default": "stills", "options": list(REFERENCE_RENDERS),
                "allow_custom": True, "description": "wfNode_scene_render_render",
            },
            "project_id": {"advanced": True, "type": "template", "description": "wfNode_scene_render_project_id"},
        },
        "outputs": ["first_frame_asset_id", "last_frame_asset_id", "video_asset_id", "camera_move",
                    "skipped_models", "model_warnings"],
        "output_labels": {
            "first_frame_asset_id": "wfOut_graybox_first_frame",
            "last_frame_asset_id": "wfOut_graybox_last_frame",
            "video_asset_id": "wfOut_graybox_video",
            "camera_move": "wfOut_camera_move",
            "skipped_models": "wfOut_skipped_models",
            "model_warnings": "wfOut_model_warnings",
        },
        "output_types": {
            "first_frame_asset_id": "asset",
            "last_frame_asset_id": "asset",
            "video_asset_id": "asset",
            "skipped_models": "number",
            "model_warnings": "json",
        },
    },
    "separate_audio": {
        "external": False,
        "category": "wfCat_audio",
        "label": "wfNode_separate_audio",
        "description": "wfNode_separate_audio_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "description": "wfNode_separate_audio_asset_id"},
            # auto = 用现在跑得起来的那个。点名一个引擎是给"装了好几个"的人用的。
            # **选项从注册表读** —— 在这里再写一遍引擎名,加一个引擎就得改两处,
            # 漏改的那处表现为"装好了却选不到"。
            "engine": {
                "type": "string",
                "default": "auto",
                "description": "wfNode_separate_audio_engine",
                "options": ["auto", *SEPARATION_ADAPTERS],
            },
        },
        "outputs": ["vocals_asset_id", "background_asset_id", "engine"],
        "output_labels": {
            "vocals_asset_id": "wfOut_vocals_asset_id",
            "background_asset_id": "wfOut_background_asset_id",
        },
        "output_types": {"vocals_asset_id": "asset", "background_asset_id": "asset"},
    },
    #: 降噪(ADR-0017)。**产出一份新素材**:音频进音频出,视频进视频出(画面原样拷贝)。
    "denoise_audio": {
        "external": False,
        "category": "wfCat_audio",
        "label": "wfNode_denoise_audio",
        "description": "wfNode_denoise_audio_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "description": "wfNode_denoise_audio_asset_id"},
            # 选项从注册表读(同分离节点)。auto = 内置的那个,它不会顺手去掉音乐。
            "engine": {
                "type": "string",
                "default": "auto",
                "description": "wfNode_denoise_audio_engine",
                "options": ["auto", *DENOISE_ADAPTERS],
            },
            "strength": {
                "type": "string",
                "default": DEFAULT_STRENGTH,
                "description": "wfNode_denoise_audio_strength",
                "options": list(STRENGTHS),
            },
        },
        "outputs": ["asset_id", "engine"],
        "output_labels": {"asset_id": "wfOut_denoised_asset_id"},
        "output_types": {"asset_id": "asset"},
    },
    "generate_subtitles": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_generate_subtitles",
        "description": "wfNode_generate_subtitles_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "description": "wfNode_generate_subtitles_sequence_id"},
            "segments": {"type": "template", "required": True, "description": "wfNode_generate_subtitles_segments"},
            "texts": {"type": "template", "description": "wfNode_generate_subtitles_texts"},
            "keep_original": {
                "type": "string",
                "default": "no",
                "options": ["yes", "no"],
                "description": "wfNode_generate_subtitles_keep_original",
            },
            "offset": {"advanced": True, "type": "number", "description": "wfNode_generate_subtitles_offset"},
            "track_id": {"advanced": True, "type": "template", "description": "wfNode_generate_subtitles_track_id"},
            # 段落不是逐字稿、而是别的对象列表时(比如循环每一项的产物),起止和文本各在哪个字段。
            "start_field": {"advanced": True, "type": "template", "default": "start", "description": "wfNode_generate_subtitles_start_field"},
            "end_field": {"advanced": True, "type": "template", "default": "end", "description": "wfNode_generate_subtitles_end_field"},
            "text_field": {"advanced": True, "type": "template", "default": "text", "description": "wfNode_generate_subtitles_text_field"},
            # 一条能用的段落都没有时:默认报错(翻译配字幕时那意味着上游出了问题);
            # 口播字幕这种"可能整片都没有口播"的场合选 yes,交出 0 条而不是让整条流程失败。
            "allow_empty": {
                "advanced": True,
                "type": "string",
                "default": "no",
                "options": ["yes", "no"],
                "description": "wfNode_generate_subtitles_allow_empty",
            },
        },
        "outputs": ["track_id", "clip_ids", "count", "sequence_id"],
        "output_types": {"clip_ids": "json", "count": "number"},
    },
    "dub_subtitles": {
        "external": False,
        "category": "wfCat_audio",
        "label": "wfNode_dub_subtitles",
        "description": "wfNode_dub_subtitles_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "description": "wfNode_dub_subtitles_sequence_id"},
            "clip_ids": {"type": "template", "required": True, "description": "wfNode_dub_subtitles_clip_ids"},
            "match_duration": {
                "type": "string",
                "default": "yes",
                "options": ["yes", "no"],
                "description": "wfNode_dub_subtitles_match_duration",
            },
            "line": {
                "type": "string",
                "default": "all",
                "options": ["all", "first", "last"],
                "description": "wfNode_dub_subtitles_line",
            },
            # 配音落轨之后原声怎么办。**「压低」不等于「听不见」** —— 闪避是 30%(≈ −10.5 dB),
            # 那是给"旁白盖在环境音之上"准备的;译配是用说话声替换说话声,压到 30% 的结果是
            # 观众同时听见两个人说话,只是一个小声点。所以给得出"静音"这一档。
            "original_audio": {
                "type": "string",
                "default": "duck",
                "options": ["duck", "mute", "keep", "separate"],
                "description": "wfNode_dub_subtitles_original_audio",
            },

            # 和「语音合成」同一对字段、同一份声明(见那里的说明)。
            "engine": {
                "type": "string",
                "default": "clone",
                "options_from": "speech_engines",
                "description": "wfNode_speech_engine",
            },
            "voice": {
                "type": "string",
                "required": True,
                "depends_on": "engine",
                "options_from": "speech_voices",
                "description": "wfNode_speech_voice",
            },
            "speed": {"advanced": True, "type": "number", "description": "wfNode_synthesize_speech_speed"},
        },
        "outputs": ["track_id", "done", "failed", "original_audio", "original_audio_note"],
        "output_labels": {
            "original_audio": "wfOut_original_audio",
            "original_audio_note": "wfOut_original_audio_note",
        },
        "output_types": {"done": "number", "failed": "number"},
    },
    "loop_foreach": {
        "external": False,
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
            "concurrency": {
                "advanced": True,
                "type": "number",
                "default": 1,
                "description": "wfNode_loop_foreach_concurrency",
            },
        },
        "outputs": ["results", "count"],
        #: 体内看得见什么 —— 执行器给体播种的正是这些(见 executors/loops)。
        #: 校验、画布就绪检查、引用选择器都读这一格,见 NESTED_BODY_TYPES 上那段。
        "body_scope": {"loop": ["item", "index"], "input": ["*inputs"]},
    },
    "loop_while": {
        "external": False,
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
        #: 没有 `input`,`loop` 底下也没有 `item`:条件循环没有「逐项」这回事,执行器只播 `loop.index`。
        "body_scope": {"loop": ["index"]},
    },
    "asset_query": {
        "external": False,
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
        "external": False,
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
        "external": False,
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
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_project_create",
        "description": "wfNode_project_create_desc",
        "config": {
            "name": {"type": "template", "required": True, "description": "wfNode_project_create_name"},
        },
        "outputs": ["project_id", "name"],
    },
    "project_sequence_create": {
        "external": False,
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
        "external": True,
        "category": "wfCat_flow",
        "label": "wfNode_call_workflow",
        "description": "wfNode_call_workflow_desc",
        "config": {
            "workflow_id": {"type": "string", "required": True, "description": "wfNode_call_workflow_workflow_id", "options_from": "callable_workflows"},
            "inputs": {"type": "object", "description": "wfNode_call_workflow_inputs"},
        },
        "outputs": ["output"],
    },
    "output": {
        "external": False,
        "category": "wfCat_flow",
        "label": "wfNode_output",
        "description": "wfNode_output_desc",
        "config": {
            "values": {"type": "object", "description": "wfNode_output_values"},
        },
        "outputs": ["output"],
    },
    "subgraph": {
        "external": False,
        "category": "wfCat_flow",
        "label": "wfNode_subgraph",
        "description": "wfNode_subgraph_desc",
        "config": {
            "inputs": {"type": "object", "description": "wfNode_subgraph_inputs"},
            "body": {"type": "graph", "description": "wfNode_subgraph_body"},
            "output": {"type": "template", "description": "wfNode_subgraph_output"},
        },
        "outputs": ["output"],
        "body_scope": {"input": ["*inputs"]},
    },
    # 浏览器自动化(RPA):在隔离浏览器会话里自动化操作网页,与发布登录完全隔离。
    # 典型链路:打开浏览器 → 导航/点击/输入/等待 → 提取 → 关闭。session 输出串起整条链。
    "browser_open": {
        "external": True,
        "category": "wfCat_browser",
        "label": "wfNode_browser_open",
        "description": "wfNode_browser_open_desc",
        "config": {
            "url": {"type": "template", "description": "wfNode_browser_open_url"},
            "session_mode": {"type": "string", "options": ["ephemeral", "named", "pool"], "description": "wfNode_browser_open_session_mode"},
            "session_name": {"type": "template", "description": "wfNode_browser_open_session_name"},
            "profile_id": {"type": "string", "description": "wfNode_browser_open_profile_id", "options_from": "browser_profiles"},
        },
        "outputs": ["session"],
    },
    "browser_navigate": {
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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
        "external": True,
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

    # 标记(位置书签)不是节点:它不执行、不连线,只是"跳到这儿"。所以它在 graph 里自成一份
    # 列表,校验也自成一条 —— 规则见 domain/markers,画板那边用的是同一份。
    from app.domain.markers import marker_errors

    errors.extend(marker_errors(graph.get("markers")))

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
            node_config = node.get("config") or {}
            node_specs = known_types[node_type]["config"]
            for key, spec in node_specs.items():
                if isinstance(spec, dict) and spec.get("required") and config_field_active(spec, node_config, node_specs):
                    value = node_config.get(key)
                    if value in (None, "") and (node_id, key) not in data_bound:
                        errors.append(f"节点 {node_id} 缺少必填配置 {key}")
            #: **运行前的校验要下到内嵌子图里,而且是整份校验。** 体是这张图的一段,它的每一种错
            #: (缺必填、引用越出作用域、空体、体里有开始节点、环、未知类型)在这里不报,就只能等
            #: 循环真跑到时才由执行器报 —— 那时工作流已经占了一个任务位、把循环之前的步骤全跑完
            #: (在「从主题到完整视频」里那是好几次付费的 AI 调用),而同一处遗漏写在顶层是当场
            #: 422、免费、且指得准。
            #:
            #: 此前这里只下探「缺必填」一项,其余的留给执行器在运行时再校验一遍 —— 而那一遍拿不到
            #: `extra_types`,于是**循环体里的插件节点一律被判「未安装或未启用」**。现在体只在这里
            #: 校验一次,带着和外层同一份节点类型。
            if node_type in NESTED_BODY_TYPES:
                where = f"节点 {node_id} 的{_body_label(node_type)}里:"
                errors.extend(
                    where + one
                    for one in validate_body_graph(node_config.get("body"), node_type, extra_types=extra_types)
                )
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
        branches = known_types.get(node_types.get(source, ""), {}).get("branches")
        if branches and handle not in (None, *branches):
            errors.append(f"条件节点的分支端点必须是 {'/'.join(branches)}: {source}")
        adjacency.setdefault(source, []).append(target)
        indegree[target] = indegree.get(target, 0) + 1
    #: 引用即依赖(见 reference_dependencies):一个节点引用了它自己的下游,就是一个环 ——
    #: 此前它照样能跑,只是取到空值,而这是最难发现的那种失败。
    for target, sources in reference_dependencies({"nodes": nodes}).items():
        for source in sources:
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
        errors.append("工作流包含环路(连线或 {{节点.…}} 引用绕回了自己),必须是有向无环图")
    return errors


#: 内嵌子图类节点(循环体 / subgraph):**由节点自己声明**体内看得见什么(`body_scope`)——
#: 作用域名 → 这个名字底下的字段。`*字段名` 表示「这个配置字段里的每个键」(和 start 的 `*params`
#: 输出同一种写法):子图的 `{{input.*}}` 是用户自己在 `inputs` 里起的名字,只有运行时那份配置知道。
#:
#: 这份声明是各方的单一真源:执行器给体播种的就是这些(run_body 逐名逐字段核对);校验据此判断
#: 体内的引用有没有越出作用域;画布的就绪检查和体内的引用选择器经 /api/workflows/node-types
#: 拿到同一格。选择器此前按「是不是子图」自己写了一份,条件循环体里也列出了拿不到的 `loop.item`。此前三方各写各的 ——
#: 校验对所有循环一律放行 `loop` 与 `input`,可条件循环(loop_while)根本不播 `input`,于是
#: 体内的 `{{input.x}}` 校验得过、运行时安静地变成空串;画布那一侧则对子图也放行 `loop`,
#: 后端却会拒绝 —— 同一张图,一边说能跑,一边说不能。
#:
#: body/output/condition 属于**内层**作用域(见 binding.interpolate_node_config 保留原文的理由),
#: 既是插值时机的依据,也是校验时不下钻的依据。binding.py 从这里取。
NESTED_BODY_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("body_scope"))
NESTED_BODY_RAW_KEYS = ("body", "output", "condition")

#: 会分支的节点(条件):**控制边**从它出发时带路由语义 —— `source_handle` 说走哪一支,没写就是
#: 第一支(「真」)。数据边从它的输出口出发只说"值从哪来",不参与路由。
#:
#: 由节点声明(`branches`),引擎路由、保存校验、规范化折叠边都读这一格。此前引擎对来自条件节点
#: 的**每一条**边都做路由,于是把 `result` 输出接进一个节点,条件为假时那个节点整个被跳过;
#: 规范化则把"同一对节点间已有数据边"的无 handle 控制边当多余的折掉,连带折掉了它的路由语义。
BRANCHING_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("branches"))


def _body_label(node_type: str) -> str:
    return "循环体" if "loop" in NODE_TYPES[node_type]["body_scope"] else "子图"


def validate_body_graph(
    body: Any, node_type: str, *, extra_types: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    """内嵌子图(循环体 / subgraph)校验:必须非空、无 start 节点、其余同 validate_graph;
    再查引用是否越出 `node_type` 声明的作用域(`body_scope`)。

    `extra_types` 和外层那次校验是同一份 —— 体里的插件节点和顶层的一样认得出来。"""
    label = _body_label(node_type)
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return [f"{label}不能为空,至少要有一个节点"]
    errors = validate_graph(body, require_start=False, extra_types=extra_types)
    errors.extend(_unresolvable_body_refs(nodes, node_type))
    return errors


def _unresolvable_body_refs(nodes: list[Any], node_type: str) -> list[str]:
    """Reject a body template that references anything outside its own scope.

    A body context is seeded with the scope names its node type declares (`body_scope`) and the
    body's own nodes — nothing else. A body node referencing an outer node like {{start.prefix}}
    therefore interpolated to the empty string: no error, no warning, just silently missing text in
    whatever the body produced. That is the worst failure mode available, so name it at validation
    time instead.

    (Making the body actually see the outer scope is not a matter of passing more context: body,
    output and condition are deliberately left un-interpolated at the outer scope so that
    {{loop.item}} / {{input.x}} survive to be resolved when the body runs. Outer values reach a
    body through the node's `inputs`, which keeps the dependency visible on the canvas.)

    Nested bodies are NOT descended into here: a nested loop/subgraph node's own
    body/output/condition belong to *its* inner scope and validate_graph checks them against that
    scope. Its `inputs`/`items` (outer-facing) are still scanned, since those resolve in *this* scope.
    """
    declared: dict[str, list[str]] = NODE_TYPES[node_type]["body_scope"]
    scope = list(declared)
    body_ids = {str(node.get("id", "")) for node in nodes if isinstance(node, dict)}
    known = set(scope) | body_ids
    #: 字段是固定几个的作用域(`loop`),字段也要对得上;字段来自配置的(`*inputs`)只有运行时知道。
    fixed = {root: set(fields) for root, fields in declared.items() if not any(one.startswith("*") for one in fields)}
    unknown: set[str] = set()
    missing: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = dict(node.get("config") or {})
        if node.get("type") in NESTED_BODY_TYPES:
            for key in NESTED_BODY_RAW_KEYS:
                config.pop(key, None)
        for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False)):
            parts = match.group(1).strip().split(".")
            root = parts[0]
            if root and root not in known:
                unknown.add(root)
            elif root in fixed and root not in body_ids and len(parts) > 1 and parts[1] not in fixed[root]:
                missing.add(f"{root}.{parts[1]}")
    errors: list[str] = []
    if missing:
        provided = "、".join(f"{root}.{field}" for root, fields in fixed.items() for field in sorted(fields))
        errors.append(f"{_body_label(node_type)}里没有 {', '.join(sorted(missing))};这里只提供 {provided}")
    if not unknown:
        return errors
    allowed = "、".join(scope)
    if "loop" in scope:
        return [*errors, f"循环体引用了循环外的节点:{', '.join(sorted(unknown))};循环体只能引用 {allowed} 与体内节点"]
    return [*errors, f"子图引用了作用域外的节点:{', '.join(sorted(unknown))};子图只能引用 {allowed} 与体内节点"]


#: 后果**落在这个应用之外**的节点:发出去的帖子、别人服务器上的改动、本机跑过的代码、
#: 用真实浏览器点下去的按钮。它们决定确认卡的权限档 —— `edit` 撤得回、`ai-cost` 最坏是花钱,
#: 这一档撤不回来。
#:
#: 浏览器节点整组算在内:一张图只要驱动浏览器,它做了什么就不再由这张图本身说了算。
#: `plugin_tool` 算在内:插件工具可以是写类的(manifest 里的 read_only 是自报的,不是判据)。
#: `call_workflow` 算在内是**保守**:它按 id 引用另一张图,扫描器跟不过去(跟过去要查库递归),
#: 「后果落在这个应用外面」的节点。**声明在节点自己身上**(`"external": True`)——
#: 加一个节点类型时作者必须在同一处说清它的后果落在哪,而不是记得去改另一头的一张表
#: (漏掉的那一个恰恰会是没人想过后果的那一个;由棘轮守着每个声明都有这一格)。
#:
#: 容器节点(loop/subgraph)本身是内部的 —— 危险的是它们的体,而体会被递归扫到。
EXTERNAL_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("external"))
INTERNAL_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if not spec.get("external"))

_MAX_GRAPH_SCAN_DEPTH = 16


#: 插件节点的类型前缀(`plugin.<插件id>.<工具名>`)。类型是**运行时**才知道的,所以它进不了
#: 上面那两张由声明派生的集合 —— 而它跑的是别人的代码,默认就该按"应用之外"算。
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX as _PLUGIN_NODE_PREFIX


def _is_external(node_type: str, types: frozenset[str]) -> bool:
    return node_type in types or (types is EXTERNAL_NODE_TYPES and node_type.startswith(_PLUGIN_NODE_PREFIX))


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
        if _is_external(ntype, types):
            found.add(ntype)
        if ntype in NESTED_BODY_TYPES:
            found |= _nodes_of_types((node.get("config") or {}).get("body"), types, _depth=_depth + 1)
    return found


def external_nodes_in_graph(graph: Any) -> set[str]:
    """图里用到的**后果在应用之外**的节点 —— 决定确认卡的权限档(见 domain/agent/confirmations)。"""
    return _nodes_of_types(graph, EXTERNAL_NODE_TYPES)


def reference_dependencies(graph: dict[str, Any]) -> dict[str, set[str]]:
    """每个节点通过 `{{节点.…}}` **引用**了本图里的哪些节点。**引用即依赖**,只在这里算。

    此前"引用了谁"和"等谁跑完"是两件脱钩的事:引擎只按边调度,而规范化只会把「顶层字段、恰好
    两段路径」的引用变成数据边 —— `{{分镜.json.shots}}`(三段)或嵌在循环 `inputs` 对象里的
    `{{start.voice_id}}` 都不产生边。于是一个节点可能在它引用的节点跑完之前就开始,取到的是空值:
    官方模板靠作者手工补的控制边碰巧排好了顺序,用户自己搭的图则不一定。

    现在拓扑排序、环路校验、引擎调度都读这一份:被引用的节点落定(跑完或被跳过)之前,引用它的
    节点不开始;引用造成环路时保存/运行就报错。只决定**先后**,不决定"该不该跑"(那仍由控制边说了算)。

    内嵌子图(循环体 / subgraph)的 body/output/condition 属于**内层**作用域,不算在这一层的依赖里;
    它们的 `inputs` / `items` 在这一层解析,算。
    """
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    ids = {str(node.get("id", "")) for node in nodes}
    deps: dict[str, set[str]] = {}
    for node in nodes:
        node_id = str(node.get("id", ""))
        config = dict(node.get("config") or {})
        if node.get("type") in NESTED_BODY_TYPES:
            for key in NESTED_BODY_RAW_KEYS:
                config.pop(key, None)
        roots = {match.group(1).strip().split(".")[0] for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False))}
        deps[node_id] = (roots & ids) - {node_id}
    return deps


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """稳定拓扑序(按 nodes 数组原顺序打破平局)。连线和引用都算依赖。假定 graph 已通过校验。"""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    indegree = {str(n["id"]): 0 for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
        indegree[str(edge["target"])] += 1
    for target, sources in reference_dependencies(graph).items():
        for source in sources:
            adjacency.setdefault(source, []).append(target)
            indegree[target] += 1
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


def as_text(value: Any) -> str:
    """一个值**当文字用**时写成什么。插值把值嵌进文字、节点把整个值当文字用,都走这一处。

    结构化的值(对象、列表)和布尔、空值写成 JSON —— 此前是 `str()`,于是对象嵌进 HTTP 请求体
    是 Python 的 repr(`{'ok': True, 'n': None}`),没有一个 JSON 解析器认它;布尔写成
    `True`,和条件节点右边照 JSON 习惯写的 `true` 永远对不上。`None` 是"没有值",写成空串。
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (bool, dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


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
    return VARIABLE_RE.sub(lambda m: as_text(lookup(m.group(1))), value)


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
    created_by: str | None,
    revision_note: str = "",
) -> Workflow:
    graph = graph if graph is not None else default_graph()
    from app.domain.workflows.normalization import normalize_graph

    extra_types = _plugin_types(db)
    graph = normalize_graph(graph, node_types={**NODE_TYPES, **extra_types})
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


def _checked_graph(db: Session, graph: Any) -> dict[str, Any]:
    """落库前的同一道:规范化 + 校验(草稿级,允许缺配置、缺开始节点)。"""
    from app.domain.workflows.normalization import normalize_graph

    extra_types = _plugin_types(db)
    normalized = normalize_graph(graph, node_types={**NODE_TYPES, **extra_types})
    errors = validate_graph(normalized, require_config=False, allow_missing_start=True, extra_types=extra_types)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    return normalized


def update_workflow(
    db: Session,
    workflow: Workflow,
    changes: dict[str, Any],
    *,
    base_graph_hash: str | None = None,
    source: str = "edit",
    created_by: str | None,
    revision_note: str = "",
) -> Workflow:
    """改名、改描述、存整份图。

    **存整份图必须带底子**(`base_graph_hash`,调用方读到的那份图的摘要):整份快照不知道别人
    刚改了什么,底子对不上就撞 `WorkflowGraphConflict`,而不是把别人的写入静默盖掉。
    只改自己那一处的写入走 `edit_workflow_graph`。
    """
    from app.domain.workflows.revisions import commit_graph_revision, replace_graph

    graph = changes.get("graph")
    if graph is not None:
        if base_graph_hash is None:
            raise WorkflowDomainError("wfErr_graphBaseMissing")
        # 图先落:撞了冲突时名字和描述也一起不动,不留半次写入。
        commit_graph_revision(
            db,
            workflow,
            replace_graph(_checked_graph(db, graph), base_graph_hash=base_graph_hash),
            source=source,
            created_by=created_by,
            note=revision_note,
        )
    if changes.get("name"):
        workflow.name = changes["name"]
    if changes.get("description") is not None:
        workflow.description = changes["description"]
    db.commit()
    db.refresh(workflow)
    return workflow


def edit_workflow_graph(
    db: Session,
    workflow: Workflow,
    change: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    source: str,
    created_by: str | None,
) -> Workflow:
    """只改图里自己那一处(按算子改图):落在**最新那份图**上,撞上并发写入就重读再合。

    和画板的 `_merge_into_latest` 同一条 —— 从最新那份出发重做一遍,不会盖掉任何人。
    """
    from app.domain.workflows.revisions import commit_graph_revision

    commit_graph_revision(
        db,
        workflow,
        lambda current: _checked_graph(db, change(current)),
        source=source,
        created_by=created_by,
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
