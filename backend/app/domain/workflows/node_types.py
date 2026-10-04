"""节点类型表(NODE_TYPES)与它的字段元数据:分组、字段标签、数据类型、编辑器。

这是节点的**元数据**接缝 —— 驱动校验、画布 UI 和智能体提示;行为接缝在 executors/registry.py。
此前它和图规则、增删改一起挤在包的 `__init__` 里(两千多行),改一个字段标签要在一个巨型文件里找位置。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers.contracts.denoise import DEFAULT_STRENGTH, STRENGTHS
from app.domain.export_presets import EXPORT_QUALITIES, EXPORT_RESOLUTIONS
from app.domain.generation.catalog import BUILTIN_MODELS, SOURCE_GROUPS, SOURCE_ROLE_LABELS
from app.domain.media_kinds import declared_media
from app.domain.scenes.operations import REFERENCE_RENDERS
from app.domain.sequences.operations import EDIT_OP_KINDS


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

#: **围着「一张图怎么跑」转的分组**:流程控制(开始、条件、循环、调子流程)、数据搬运(请求、模板、
#: 取 JSON、字符串处理)、知识库的查与写。它们交出的是给下游连线用的中间值 —— 一个状态码、一段拼好的
#: 字符串、一串检索结果 —— 不是一样「手里这东西接下来变成了什么」的新内容。
#:
#: 创意画板只放**内容变换**(见 boards.transforms,ADR 0021 修订):这几组的节点即使声明了
#: `surfaces: ["board"]` 也不上画板,棘轮钉着(test_board_producers)。按分组判而不是按输出类型判,
#: 因为 template / text_transform 的输出也是文字 —— 输出类型分不开「一段译文」和「一段拼好的请求体」。
WIRING_CATEGORIES: frozenset[str] = frozenset({"wfCat_flow", "wfCat_data", "wfCat_knowledge"})

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
    "allow_missing": "wfField_allow_missing",
    "allow_error_page": "wfField_allow_error_page",
    "frame": "wfField_frame",
    "sources": "wfField_sources",
    "checked": "wfField_checked",
    "matched": "wfField_matched",
    "paraphrased": "wfField_paraphrased",
    "unmatched": "wfField_unmatched",
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
    "max_items": "wfField_max_items",
    "on_item_error": "wfField_on_item_error",
    "failure_note": "wfField_failure_note",
    "dropped": "wfField_dropped",
    "trim_overflow": "wfField_trim_overflow",
    "until": "wfField_until",
    "strength": "wfField_strength",
    "exact": "wfField_exact",
    "expression": "wfField_expression",
    "file_path": "wfField_file_path",
    "fail_on_error": "wfField_fail_on_error",
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
    "required_params": "wfField_required_params",
    "param_options": "wfField_param_options",
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
    "table_limit": "wfField_table_limit",
    "size": "wfField_size",
    "batches": "wfField_batches",
    "total": "wfField_total",
    "title": "wfField_title",
    "tool_name": "wfField_tool_name",
    "top_p": "wfField_top_p",
    "track_id": "wfField_track_id",
    "url": "wfField_url",
    "url_contains": "wfField_url_contains",
    "value": "wfField_value",
    "values": "wfField_values",
    "voice": "wfField_voice",
    "wait_ms": "wfField_wait_ms",
    "width": "wfField_width",
    "grid": "wfField_grid",
    "gutter": "wfField_gutter",
    "parser": "wfField_parser",
    "workflow_id": "wfField_workflow_id",
    # 下列主要出现在输出端,也可被同名配置字段复用。
    "applied": "wfField_applied",
    "assets": "wfField_assets",
    "audio_track_id": "wfField_audio_track_id",
    "columns": "wfField_columns",
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
    "sentences": "wfField_sentences",
    "sent": "wfField_sent",
    "source_asset_id": "wfField_source_asset_id",
    "status": "wfField_status",
    "timed_text": "wfField_timed_text",
    "timeline_end": "wfField_timeline_end",
    "timeline_start": "wfField_timeline_start",
    "trimmed": "wfField_trimmed",
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
    "resolution": "wfField_resolution",
    "quality": "wfField_quality",
    "ai_label": "wfField_ai_label",
    "source_group": "wfField_source_group",
    "entity_ids": "wfField_entity_ids",
    "entity_id": "wfField_entity_id",
    "entities": "wfField_entities",
    "max_shots": "wfField_max_shots",
    "shot_seconds": "wfField_shot_seconds",
    "aspect": "wfField_aspect",
    "tag": "wfField_tag",
    "expressions": "wfField_expressions",
    "consent": "wfField_consent",
    "for_speech": "wfField_for_speech",
    "audio_asset_id": "wfField_audio_asset_id",
    "scope": "wfField_scope",
    "found": "wfField_found",
    "voice_engine": "wfField_voice_engine",
    "voice_id": "wfField_voice_id",
    "created": "wfField_created",
    "added": "wfField_added",
    "role": "wfField_role",
    "if_exists": "wfField_if_exists",
    "cues": "wfField_cues",
    "chunk_count": "wfField_chunk_count",
    "generated_count": "wfField_generated_count",
    "reused_count": "wfField_reused_count",
    "skipped_ranges": "wfField_skipped_ranges",
    "skipped_note": "wfField_skipped_note",
    "kept_text": "wfField_kept_text",
    "source_lang": "wfField_source_lang",
    "max_seconds": "wfField_max_seconds",
    # 自媒体分析的几个节点。
    "link": "wfField_link",
    "platform": "wfField_platform",
    "expect": "wfField_expect",
    "data": "wfField_data",
    "profile": "wfField_profile",
    "duration_unit": "wfField_duration_unit",
    "utc_offset": "wfField_utc_offset",
    "unescape_html": "wfField_unescape_html",
    "max_height": "wfField_max_height",
    "error": "wfField_error",
    "id": "wfField_id",
    "account": "wfField_account",
    "stats": "wfField_stats",
    "summary": "wfField_summary",
    "table": "wfField_table",
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


def node_title(node: dict[str, Any], types: dict[str, dict[str, Any]] | None = None) -> str:
    """报错里提到一个节点时叫它什么:节点的标题;没起名就是节点类型的显示名(按这次请求的语言);类型认不出(插件没装)
    就是它的 id。和画布就绪清单的节点名同一个取法(analyze.ts 的 nodeName)—— 同一个问题两边说的是同一个名字。"""
    from app.core.i18n import get_current_locale, pick_text, tr

    name = node.get("name")
    #: 官方模板的图在建图那一刻才定语言,之前节点名是 {zh, en}(见 templates.localised_names)。
    if isinstance(name, dict):
        name = pick_text(name, get_current_locale())
    if isinstance(name, str) and name.strip():
        return name.strip()
    meta = (types or NODE_TYPES).get(str(node.get("type") or ""))
    label = str((meta or {}).get("label") or "").strip()
    return tr(label) if label else str(node.get("id") or "")


def layer_titles(nodes: list[Any], types: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    """一层图里每个节点在报错里叫什么(node_title);**同一层里撞名的**(两个都没起名的「文本模板」)后面带上 id ——
    「「文本模板」引用了…,可「文本模板」没接进流程」读不出说的是哪两个。和画布 analyze.ts 的 layerDisplayNames 同一条。"""
    base = {str(node.get("id", "")): node_title(node, types) for node in nodes if isinstance(node, dict)}
    counts: dict[str, int] = {}
    for title in base.values():
        counts[title] = counts.get(title, 0) + 1
    return {node_id: f"{title}({node_id})" if counts[title] > 1 else title for node_id, title in base.items()}


def reference_label(parts: list[str], nodes: dict[str, dict[str, Any]], types: dict[str, dict[str, Any]] | None = None) -> str:
    """一条引用(按点号拆开)在一句话里怎么说:「节点的名字 · 输出的显示名 · 子路径」;根不是这一层的节点(作用域名、
    不存在的节点)就按段说。和画布的 workflowRefCatalog.look / refLabel 同一个取法(节点没起名的用 id)—— 句子里不摆 `{{…}}`。"""
    from app.core.i18n import tr

    node = nodes.get(parts[0]) if parts else None
    if node is None:
        return " · ".join(parts)
    name = node.get("name")
    head = [name.strip() if isinstance(name, str) and name.strip() else str(node.get("id") or "")]
    if len(parts) > 1:
        meta = (types or NODE_TYPES).get(str(node.get("type") or "")) or {}
        output = parts[1]
        head.append(tr(output_label(output, meta)) if output in (meta.get("outputs") or ()) else output)
    return " · ".join([*head, *parts[2:]])


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
    # 场景卡(分镜)。画板把上游的场景接进来时,靠它判断这一格能不能接到那个字段上。
    ("scene_id", "scene"),
)

#: 字段装的是**另一个系统里的编号**:ComfyUI 的任务号、网盘的 fs_id、对象存储的对象路径、翻页游标。
#: 它指向的东西不在这个工作区里,创作者既写不出也认不出 —— 值从上游接(列清单、跑工作流的那一步交出来的),
#: 或者由智能体从上一次调用里抄。命名推不出来(`prompt_id` 和 `project_id` 长得一样),所以只认声明:
#: 内置节点写 `"data_type": "external_id"`,插件在 input_schema 里写 `"format": "external_id"`(见 plugins.nodes)。
#: 画板据此判一个工具是不是「按编号去外面取东西」(boards.transforms 的 `external_id`);选择器棘轮据此知道
#: 这个 `*_id` 不是工作区里的实体(tests/test_entity_fields_have_a_picker)。
EXTERNAL_ID = "external_id"


def config_media(spec: Any) -> tuple[str, ...]:
    """这个素材字段收哪几种素材(`"media"`:一种写字符串,几种写列表);没声明就是空 —— 哪种都收。

    素材选择器只列这几种,画板上只有这几种格子接得上(boards.tools.bindable_kinds)。此前「素材转写」
    没声明,画板格子上写着「接图片、视频或音频」,而转写只吃有声音的那两种。
    """
    return declared_media(spec.get("media") if isinstance(spec, dict) else None)


def config_entity_kinds(spec: Any) -> tuple[str, ...]:
    """这个资产字段收哪几种资产:选项来源点名了种类(`entities.character`)就只收那一种;没点名是哪种都收。

    和素材字段的 `media` 同一个意思:下拉只列这一种,画板上也只有这一种资产格有这项能力(「生成表情」只挂在
    人物上,场景、道具没有表情 —— boards.transforms.host_entity_kinds)。
    """
    source = str(spec.get("options_from") or "") if isinstance(spec, dict) else ""
    prefix = "entities."
    return (source[len(prefix):],) if source.startswith(prefix) else ()


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
    "dropped": "number",
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
    "trimmed": "number",
    "waited": "number",
}
#: `scene`:一个 3D 场景的 id(「按文字搭 3D 场景」交出的那个)—— 画板据此把它落成一格 3D 场景格。
_WORKFLOW_DATA_TYPES = frozenset({"text", "asset", "sequence", "scene", "number", "json", "any"})


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


#: 节点能在哪些地方用:`"surfaces": ["workflow", "board"]` 的节点同时是创意画板上内容格的一项能力(吃素材 / 文字 /
#: 3D 场景的,挂在那几种格子上)或空格子的一种填法(凭空产出素材的)—— 见 boards.producers 和 boards.transforms,
#: 注册表**从这份声明里读**,挂在哪也按字段声明推,不在画板那边另列一张表。没写就只在工作流里。
#:
#: **声明了也要过一道规矩:画板上只有内容变换**(boards.transforms.content_transform_gap,ADR 0021 修订)——
#: 吃画板上的内容(素材 / 文字 / 3D 场景)或凭空产出素材,交出画板摆得下的内容(素材,或点名落板的文字),
#: 不在 WIRING_CATEGORIES 里,必填字段没有只有工程师看得懂的(映射、原始 JSON、代码)。声明了却过不了的,
#: 棘轮当场报出来,注册表也不收。不上画板的还有:llm / ai_generate / synthesize_speech 和画板内置的写字、
#: 生成、念重复;timeline_* / publish 副作用太大(ADR 0021 决定 3)。
#:
#: `"board_outputs"`:上了画板的节点,哪几个输出落成画布上的新格子(缺省是全部)。一个节点在工作流里
#: 交出的东西有一半是给下游连线用的(字数、状态码、引擎名、输入素材的 id),摊在画板上全是噪音 ——
#: 视频转 GIF 还会把**输入**那段视频原样再摆一格出来。文字输出只有在这里**点了名**才算这个节点的产出
#: (一段转写 vs 一行状态摘要,光看类型分不开)。
#:
#: `"board_group"` / `"board_description"`:它按吃的是什么内容归哪一组(词表见 boards.transforms.BOARD_GROUPS,
#: 能力图标认不出时的兜底)、一句给创作者看的说明(i18n key,能力面板上那一句)。工作流的节点说明是写给
#: 搭流程的人的(输出口、`{{…}}` 引用),画板上不照搬。
#:
#: **指向某样东西的字段给选择器,不给文本框**(棘轮 test_entity_fields_have_a_picker):场景、镜头、项目、
#: 时间线、轨道、账号、连接、工作流……值是一个 id,让人去别处抄一串十六进制回来是这张表的失职。
#: 清单从哪来写在声明里 —— `options_from`(后端 field_options 现查,`depends_on` 的值作为 parent 带上)、
#: `options`(闭集)、`editor`(专用控件),素材字段由 data_type 给素材选择器。模板字段挂了选择器仍然能写
#: `{{上游.输出}}`:表单在工作流里对模板字段收「选一项,或一段引用」(见 nodeForms/NodeConfigForm)。
#:
#: `"sole_option_default": True`:**留空 = 清单里只有一项时用那一项**,多于一项时运行时不猜、报出来。
#: 是默认而不是预选:表单不替人把它写进配置(父字段常常是上游接进来的,那一刻清单还不知道),只把它
#: 显示成当前值;真正做决定的是运行时的同一条规矩(插件连接的 resolve_instance、渲白模的镜头)。
#:
#: `"one_of": "<组名>"`:**同组的字段恰好填一个**(浏览器上传的素材 / 本机路径)。运行前校验在这里报
#: 「都填了」和「都没填」;表单里一格填了,同组其余的就收起来,从源头上填不出两个;就绪检查同一条规矩
#: (见 nodeForms/fieldActivation)。接了上游(数据边)或写了 `{{…}}` 引用都算填了。
#:
#: **前面是引用、后面是兜底**可以:同组按声明的顺序,最后一个填了的之前,填了的每一格都是整格一条引用
#: (`{{上游.值}}`)或接了数据边 —— 运行时按顺序取第一个非空的值(点击、等待、按名字找资产的执行器都这么取),
#: 上游给空就落到兜底那一格。执行器不按顺序取、两样都给就报错的组(浏览器上传的素材 / 路径,见
#: host_files.upload_source)在字段上写 `"one_of_strict": True`:那一组照旧恰好填一个。
NODE_TYPES: dict[str, dict[str, Any]] = {
    "start": {
        "external": False,
        "category": "wfCat_flow",
        "label": "wfNode_start",
        "description": "wfNode_start_desc",
        "config": {
            #: 一行一个参数:名字 → 默认值。面板上用开始节点专用的控件(名字、默认值、「必填」开关 —— 前端
            #: StartParamsField),它同时编辑 `required_list` 点名的那一格:必填是**那一行自己的**,改名、删行时跟着走。
            "params": {
                "type": "object",
                "editor": "start_params",
                "required_list": "required_params",
                "options_map": "param_options",
                "description": "wfNode_start_params",
            },
            #: 哪几个参数**跑之前必须有值**:params 里参数名的**列表**,按参数的顺序(保存时规范化,见
            #: normalization.canonicalize_start_params)。运行前校验按它查(连同这次运行传进来的值,见
            #: graph_rules.with_run_params):空着就当场拒,说清是哪一个。官方模板里要用户自己填的商品名、卖点、主题
            #: 都点名在这里 —— 空着跑的话,模型对着空白写脚本,后面的付费生成照样扣费。
            #: 此前是一格逗号分隔的字:同一个名字写两遍,参数改名、删行之后它不跟着变。旧形状由迁移和图升级改成列表
            #: (graph_upgrade.start_required_params_become_a_list)。`edited_by`:不单独出一格,由参数那一格的控件编辑。
            "required_params": {"type": "list", "edited_by": "params", "description": "wfNode_start_required_params"},
            #: 哪几个参数**只能从几项里选**:参数名 → 选项列表(值、标签、一句说明;选它要什么前置条件 `requires`,
            #: 和模板库前置条件同一个检查键,见 template_requirements.CHECKS)。面板上那一行的默认值栏是下拉;
            #: 运行前值不在选项里就拦,选中的那一项没备好也拦(engine._check_chosen_options)。没声明的参数照旧自由输入。
            "param_options": {"type": "object", "edited_by": "params", "description": "wfNode_start_param_options"},
        },
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
        #: 输出的结构写在哪一格配置里(那一格是一份 JSON Schema):`json` 长什么样由 `json_schema` 说。
        #: 引用它的地方(具名输出、入参……)据此列出 `{{节点.json.字段}}` 让人挑,而不是只能挑整个 `json`、
        #: 再手敲子路径。界面只读这份声明,不按节点类型认(见前端 workflows/workflowRefCatalog)。
        "output_schema_from": {"json": "json_schema"},
    },
    "plugin_tool": {
        "external": True,
        "category": "wfCat_plugin",
        "label": "wfNode_plugin_tool",
        "description": "wfNode_plugin_tool_desc",
        "config": {
            "plugin_id": {"type": "string", "required": True, "options_from": "plugin_packages"},
            "tool_name": {"type": "string", "required": True, "depends_on": "plugin_id", "options_from": "plugin_tools"},
            # 同一个插件可以接多个连接;留空且只有一个可用连接时自动用它(plugins.nodes.resolve_instance)。
            "instance_id": {"advanced": True, "type": "string", "description": "wfNode_plugin_tool_instance_id",
                            "depends_on": "plugin_id", "options_from": "plugin_instances", "sole_option_default": True},
            "input": {"type": "object", "description": "wfNode_plugin_tool_input"},
        },
        "outputs": ["output"],
    },
    "transcribe_asset": {
        "external": False,
        "surfaces": ["workflow", "board"],
        "board_outputs": ["text"],
        "board_group": "audio", "board_description": "wfNode_transcribe_asset_board",
        "category": "wfCat_audio",
        "label": "wfNode_transcribe_asset",
        "description": "wfNode_transcribe_asset_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": ["audio", "video"],
                         "description": "wfNode_transcribe_asset_asset_id"},
            #: 转写提供方(ADR 0032):本机引擎和插件连接并列,空 = 按运行者的默认。
            "engine": {
                "type": "string",
                "description": "wfNode_transcribe_asset_engine",
                "options_from": "providers.transcription",
            },
        },
        "outputs": ["text", "timed_text", "segments", "sentences", "language", "transcript_id", "duration"],
        "output_types": {"segments": "json", "sentences": "json", "duration": "number"},
    },
    #: 画板上的时间线格导出也跑这一个(内置产出者 `sequence_export`,见 boards.producers):时间线由格子给,
    #: 分辨率 / 画质 / 「AI 生成」标识读的是这同一份字段声明,和剪辑页导出同一组取值(render.EXPORT_*)。
    "export_sequence": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_export_sequence",
        "description": "wfNode_export_sequence_desc",
        "output_media": {"asset_id": "video"},
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences"},
            "resolution": {"type": "string", "default": "original", "options": list(EXPORT_RESOLUTIONS),
                           "description": "wfNode_export_sequence_resolution"},
            "quality": {"type": "string", "default": "standard", "options": list(EXPORT_QUALITIES),
                        "description": "wfNode_export_sequence_quality"},
            "ai_label": {"type": "string", "default": "yes", "options": ["yes", "no"],
                         "description": "wfNode_export_sequence_ai_label"},
        },
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
    #: 从链接下载一条视频 / 音频进素材库 —— 和素材库「从链接导入」同一个任务(assets.from_url,yt-dlp)。
    #: 需要登录才下得到的(抖音、会员视频)借浏览器池档案的登录态;只借这一次,下完就关。
    "import_url": {
        "external": True,
        "category": "wfCat_asset",
        "label": "wfNode_import_url",
        "description": "wfNode_import_url_desc",
        "config": {
            "url": {"type": "template", "required": True, "description": "wfNode_import_url_url"},
            "kind": {"type": "string", "options": ["video", "audio"], "default": "video",
                     "description": "wfNode_import_url_kind"},
            "profile_id": {"type": "string", "options_from": "browser_profiles", "label": "wfField_browser_profile",
                           "description": "wfNode_import_url_profile_id"},
            "max_height": {"advanced": True, "type": "number", "default": 1080, "description": "wfNode_import_url_max_height"},
            "fail_on_error": {"advanced": True, "type": "string", "options": ["yes", "no"], "default": "yes",
                              "label": "wfField_download_fail_on_error", "description": "wfNode_import_url_fail_on_error"},
        },
        "outputs": ["asset_id", "name", "error"],
        "output_types": {"name": "text", "error": "text"},
    },
    "inspect_sequence": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_inspect_sequence",
        "description": "wfNode_inspect_sequence_desc",
        "config": {"sequence_id": {"type": "template", "required": True, "options_from": "sequences"}},
        "outputs": ["sequence_id", "revision", "tracks", "duration", "video_track_id", "audio_track_id"],
    },
    "timeline_append": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_timeline_append",
        "description": "wfNode_timeline_append_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences", "description": "wfNode_timeline_append_sequence_id"},
            "asset_id": {"type": "template", "required": True, "description": "wfNode_timeline_append_asset_id"},
            "track_id": {"advanced": True, "type": "template", "depends_on": "sequence_id", "options_from": "sequence_tracks",
                         "description": "wfNode_timeline_append_track_id"},
            "start": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_start"},
            "end": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_end"},
            "at": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_at"},
            "max_duration": {"advanced": True, "type": "number", "description": "wfNode_timeline_append_max_duration"},
            #: 加速到上限仍放不下时:默认让它超出去(超出多少看 timeline_end);选 yes 就把尾巴裁掉,裁了几秒交在 trimmed。
            "trim_overflow": {
                "advanced": True,
                "type": "string",
                "default": "no",
                "options": ["yes", "no"],
                "description": "wfNode_timeline_append_trim_overflow",
            },
        },
        #: duration 是这一段在时间线上**实际**占几秒(timeline_end − timeline_start):素材比截取范围短时出点被夹到
        #: 素材末尾,比计划的短 —— 下游按它定旁白最长多久、字幕裁到哪,不按计划里写的秒数。
        "outputs": ["clip_id", "timeline_start", "timeline_end", "duration", "trimmed", "sequence_id"],
    },
    "timeline_add_track": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_timeline_add_track",
        "description": "wfNode_timeline_add_track_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences"},
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
        "config": {"sequence_id": {"type": "template", "required": True, "options_from": "sequences"}},
        "outputs": ["removed", "sequence_id"],
    },
    "timeline_cut_ranges": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_timeline_cut_ranges",
        "description": "wfNode_timeline_cut_ranges_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences"},
            #: 片段属于上面那条时间线:换了时间线,旧片段就该清掉(编辑器按 depends_on 清),否则跑到这一步才说
            #: 「片段不在这条时间线上」。没有选项源 —— 片段是同一次运行里上游刚放上去的,只该从上游接。
            "clip_id": {"type": "template", "required": True, "depends_on": "sequence_id",
                        "description": "wfNode_timeline_cut_ranges_clip_id"},
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
            #: 给了逐字稿段落(转写节点的 segments),就顺手交出删完之后剩下的原话(kept_text)。
            "segments": {
                "advanced": True,
                "type": "template",
                "description": "wfNode_timeline_cut_ranges_segments",
            },
        },
        "outputs": ["removed", "removed_seconds", "ranges", "skipped_ranges", "skipped_note", "kept_text",
                    "sequence_id", "revision"],
        "output_types": {"removed": "number", "removed_seconds": "number", "ranges": "json", "skipped_ranges": "json",
                         "revision": "number"},
    },
    "edit_timeline": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_edit_timeline",
        "description": "wfNode_edit_timeline_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences"},
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
            "kind": {"type": "string", "required": True, "description": "wfNode_ai_generate_kind", "options": ["image", "video", "audio"]},
            #: **不标必填。** 提示词要不要写是模型说的(描述符的 `prompt`:放大工作流不收、视频配声可以不写),
            #: 由生成漏斗按描述符判;这里标必填的话,不收提示词的模型永远过不了运行前校验。界面按选中的
            #: 模型把它标成必填 / 可选 / 藏起来(见前端 WorkflowsView 与 analyze)。
            "prompt": {"type": "template"},
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
            #: 点名资产库里的人物 / 场景 / 道具(ADR 0027 的 `@资产`):提示词描述拼进提示词,参考图按模型收得下的
            #: 张数挂上 —— 和 AI 工作台、画板、智能体同一条路(domain/entities/mentions)。挑几个就是一串 id;
            #: 也可以是上游给的一串(`{{…}}`)。
            "entity_ids": {
                "type": "template", "options_from": "entities", "editor": "id_list",
                "description": "wfNode_ai_generate_entity_ids",
            },
            #: 挂了驱动音频(说话照片、对口型,即数字人)时必须选上,生成漏斗才放行(ADR 0028 §5)。别的生成用不上,
            #: 所以不标必填、收在高级里;挂了驱动音频时,检查器把它提到第一屏并标必填(见前端 NodeInspector 的 drivesDigitalHuman)。
            "consent": {"advanced": True, "type": "string", "options": ["yes"], "description": "wfNode_talking_consent"},
        },
        #: asset_id 是**封面**(下游多数节点只接一份),asset_ids 是这次出的全部 ——
        #: 图像接口的 n 能一次出好几张,不声明的话下游连不到它们(执行体一直在返回)。
        "outputs": ["asset_id", "asset_ids", "generation_id"],
    },
    #: 文档(ADR 0031):一份 PDF / Word / PPT / Excel 素材 → 解析出的 Markdown。用最新成功的那份解析;
    #: 还没解析过就先用本地解析解一遍再给。接写作、翻译、生成。
    "document_to_markdown": {
        "external": False,
        "category": "wfCat_knowledge",
        "label": "wfNode_document_to_markdown",
        "description": "wfNode_document_to_markdown_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": "document",
                         "description": "wfNode_document_to_markdown_asset_id"},
            #: 用哪一家的解析(本地 / MinerU 这类插件连接)。空 = 已有的最新一份,没有就本地解析一遍。
            "parser": {"type": "string", "options_from": "providers.document_parse", "description": "wfNode_document_to_markdown_parser"},
            "first": {"advanced": True, "type": "number", "label": "wfField_first_section", "description": "wfNode_document_to_markdown_first"},
            "last": {"advanced": True, "type": "number", "label": "wfField_last_section", "description": "wfNode_document_to_markdown_last"},
        },
        "outputs": ["markdown", "title", "sections", "total", "unit"],
        "output_labels": {"sections": "wfOut_document_sections", "total": "wfOut_document_total", "unit": "wfOut_document_unit"},
        "output_types": {"markdown": "text", "title": "text", "sections": "json", "total": "number", "unit": "text"},
    },
    "video_to_gif": {
        "external": False,
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_id"],
        #: 落板的输出是哪种素材(见 boards.transforms.output_kinds):GIF 是一张动图,不是一段视频。
        "output_media": {"asset_id": "image"},
        "board_group": "video", "board_description": "wfNode_video_to_gif_board",
        "category": "wfCat_asset",
        "label": "wfNode_video_to_gif",
        "description": "wfNode_video_to_gif_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": "video", "description": "wfNode_video_to_gif_asset_id"},
            "fps": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_fps"},
            "width": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_width"},
            "start": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_start"},
            "duration": {"advanced": True, "type": "number", "description": "wfNode_video_to_gif_duration"},
        },
        "outputs": ["asset_id", "source_asset_id"],
    },
    #: 图片格的一项能力:把一张宫格拼图(九宫格表情包、四格分镜、多角度设定图)等分切成几张单图。本机处理、不花钱;
    #: 画板上切出来的几格照原来的宫格排在右边(`board_columns` 点名交出列数的那个输出,见 boards.canvas._derive)。
    "image_grid_split": {
        "external": False,
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_ids"],
        "board_columns": "columns",
        "output_media": {"asset_ids": "image"},
        "board_group": "image", "board_description": "wfNode_image_grid_split_board",
        "category": "wfCat_asset",
        "label": "wfNode_image_grid_split",
        "description": "wfNode_image_grid_split_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": "image", "description": "wfNode_image_grid_split_asset_id"},
            "grid": {"type": "string", "default": "3x3",
                     "options": ["2x2", "3x3", "1x2", "2x1", "1x3", "3x1", "2x3", "3x2", "3x4", "4x3"],
                     "description": "wfNode_image_grid_split_grid"},
            "gutter": {"type": "string", "default": "keep", "options": ["keep", "trim"],
                       "description": "wfNode_image_grid_split_gutter"},
        },
        "outputs": ["asset_ids", "asset_id", "count", "columns", "source_asset_id"],
        "output_types": {"asset_ids": "asset", "count": "number", "columns": "number"},
        "wiring_outputs": ["count", "columns", "source_asset_id"],
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
            #: `"interpolate": "json"`:请求体是一段 JSON 时,引用按 JSON 的规矩填进去 —— 引号里的
            #: 转义成字符串内容,引号外的写成 JSON 字面量(见 graph_rules.interpolate_json_text)。
            #: 此前原样拼接,一段带引号或换行的 LLM 回答就把请求体弄成了坏的 JSON。
            "body": {"type": "template", "interpolate": "json", "label": "wfField_request_body",
                     "description": "wfNode_http_request_body"},
            "fail_on_error": {
                "advanced": True,
                "type": "string",
                "default": "yes",
                "options": ["yes", "no"],
                "description": "wfNode_http_request_fail_on_error",
            },
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
    #: 把一串拆成等长的几批 —— 全量分析、分批拉取的公共积木。此前「分批」只有手写循环一条
    #: 路,而循环体拿不到「第几批的内容」;拆批之后 loop_foreach 直接逐批跑。
    "list_chunk": {
        "external": False,
        "category": "wfCat_data",
        "label": "wfNode_list_chunk",
        "description": "wfNode_list_chunk_desc",
        "config": {
            "items": {"type": "template", "required": True, "description": "wfNode_list_chunk_items"},
            "size": {"type": "number", "default": 100, "description": "wfNode_list_chunk_size"},
        },
        "outputs": ["batches", "count", "total"],
        "output_types": {"batches": "json", "count": "number", "total": "number"},
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
            # 查找串为空时 replace 会在每个字符之间插一遍替换串 —— 只在用得上它的两种处理里出现、必填。
            "find": {"type": "template", "required": True, "active_when": {"op": ["replace", "regex_extract"]},
                     "description": "wfNode_text_transform_find"},
            "replace": {"type": "template", "active_when": {"op": "replace"}, "description": "wfNode_text_transform_replace"},
        },
        "outputs": ["text", "length"],
    },
    #: 自媒体分析(见 domain/social_media、templates_analysis):认链接、把作品 / 评论整理成同一个形状并算指标。
    #: 不取数 —— 取数是 TikHub 插件节点、浏览器节点的事;这两个节点让两条取数路交出同一份东西。
    #: 认链接要跟短链的跳转(v.douyin.com、xhslink.com、b23.tv),所以算外部节点。
    "social_link": {
        "external": True,
        "category": "wfCat_data",
        "label": "wfNode_social_link",
        "description": "wfNode_social_link_desc",
        "config": {
            "link": {"type": "template", "required": True, "description": "wfNode_social_link_link"},
            "platform": {"type": "template", "description": "wfNode_social_link_platform"},
            "expect": {"type": "string", "options": ["account", "video"], "default": "account",
                       "description": "wfNode_social_link_expect"},
        },
        "outputs": ["platform", "kind", "id", "url"],
        "output_types": {"platform": "text", "kind": "text", "id": "text", "url": "text"},
    },
    "social_metrics": {
        "external": False,
        "category": "wfCat_data",
        "label": "wfNode_social_metrics",
        "description": "wfNode_social_metrics_desc",
        "config": {
            "data": {"type": "template", "required": True, "description": "wfNode_social_metrics_data"},
            "kind": {"type": "string", "options": ["posts", "comments"], "default": "posts",
                     "description": "wfNode_social_metrics_kind"},
            "profile": {"type": "template", "active_when": {"kind": "posts"},
                        "description": "wfNode_social_metrics_profile"},
            "limit": {"type": "number", "default": 30, "description": "wfNode_social_metrics_limit"},
            "table_limit": {"advanced": True, "type": "number", "description": "wfNode_social_metrics_table_limit"},
            "duration_unit": {"advanced": True, "type": "string", "options": ["auto", "seconds", "milliseconds"],
                              "default": "auto", "active_when": {"kind": "posts"},
                              "description": "wfNode_social_metrics_duration_unit"},
            "utc_offset": {"advanced": True, "type": "number", "default": 8, "description": "wfNode_social_metrics_utc_offset"},
            #: 评论原文做过 HTML 转义的来源(B 站评论接口)才选 yes;没转义的来源解了反而改掉用户的原文。
            "unescape_html": {"advanced": True, "type": "string", "options": ["no", "yes"], "default": "no",
                              "active_when": {"kind": "comments"}, "description": "wfNode_social_metrics_unescape_html"},
        },
        "outputs": ["items", "count", "account", "stats", "summary", "table"],
        "output_types": {"items": "json", "count": "number", "account": "json", "stats": "json",
                         "summary": "text", "table": "text"},
    },
    #: 模型写的报告里加了引号的话,逐条核对是不是取回来的原文;找不到的去掉引号、标为转述(见 domain/quotes)。
    #: 分析类模板在存笔记之前都过它 —— 提示词里写了「只引用原文」,模型仍会把归纳的话放进引号。
    "quote_check": {
        "external": False,
        "category": "wfCat_data",
        "label": "wfNode_quote_check",
        "description": "wfNode_quote_check_desc",
        "config": {
            #: 「texts」在别的节点上是「逐条文本」;这里是要核对的那几段,名字单独给。
            "texts": {"type": "object", "label": "wfField_quote_texts", "description": "wfNode_quote_check_texts"},
            "sources": {"type": "object", "description": "wfNode_quote_check_sources"},
        },
        "outputs": ["texts", "checked", "matched", "paraphrased", "unmatched", "summary"],
        "output_labels": {"texts": "wfOut_quote_texts"},
        "output_types": {"texts": "json", "checked": "number", "matched": "number", "paraphrased": "number",
                         "unmatched": "json", "summary": "text"},
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
                "default": "builtin:clone",
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
            "body": {"type": "template", "label": "wfField_notify_body", "description": "wfNode_notify_body"},
        },
        "outputs": ["sent"],
    },
    "translate": {
        "external": False,
        "surfaces": ["workflow", "board"],
        "board_outputs": ["text"],
        "board_group": "text", "board_description": "wfNode_translate_board",
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
            #: 翻译提供方(ADR 0032):Google 免费、对话模型、插件连接并列;空 = 按运行者的默认。
            "engine": {"type": "string", "description": "wfNode_translate_engine", "options_from": "providers.translation"},
            "profile_id": {"type": "string", "description": "wfNode_translate_profile_id", "depends_on": "engine", "options_from": "chat_connections", "active_when": {"engine": "builtin:chat"}},
            # 一条连接上常常挂着好几个模型 —— 「用哪条连接」和「用哪个模型」是两个问题。
            # 留空按这条连接的 chat 能力解析(和 llm 节点同一条路)。
            "model": {"type": "string", "description": "wfNode_translate_model", "depends_on": "profile_id", "options_from": "chat_models", "allow_custom": True, "active_when": {"engine": "builtin:chat"}},
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
            #: 原文是什么语言(接转写节点的 language)。和目标语言相同时直接拒:译成同一种语言只是白花钱。空 = 不比。
            "source_lang": {"advanced": True, "type": "template", "description": "wfNode_translate_lines_source_lang"},
            #: 译文是不是要拿去配音:是的话简繁算同一种语言(念出来一样),原文中文时译成另一种中文字形也拦。
            "for_speech": {"advanced": True, "type": "string", "default": "no", "options": ["yes", "no"],
                           "description": "wfNode_translate_lines_for_speech"},
            #: 翻译提供方(ADR 0032):Google 免费、对话模型、插件连接并列;空 = 按运行者的默认。
            "engine": {"type": "string", "description": "wfNode_translate_engine", "options_from": "providers.translation"},
            # 选了 ai 之后「用哪条连接」立刻变成要紧事,所以它不在高级里。
            # depends_on:换引擎就换了这一格的意义(google 下它没用),声明出来界面才会跟着变。
            "profile_id": {"type": "string", "description": "wfNode_translate_profile_id", "depends_on": "engine", "options_from": "chat_connections", "active_when": {"engine": "builtin:chat"}},
            # 一条连接上常常挂着好几个模型 —— 「用哪条连接」和「用哪个模型」是两个问题。
            # 留空按这条连接的 chat 能力解析(和 llm 节点同一条路)。
            "model": {"type": "string", "description": "wfNode_translate_model", "depends_on": "profile_id", "options_from": "chat_models", "allow_custom": True, "active_when": {"engine": "builtin:chat"}},
        },
        "outputs": ["texts", "count"],
        "output_types": {"texts": "json", "count": "number"},
    },
    #: 人声/背景音分离(ADR-0016)。**产出两份新素材,原素材一个字节不动。**
    #: 3D 白模(见 executors/scenes.py 与 domain/scenes/render)。
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
    #: 画板上是 **3D 场景格的一种填法**(和「渲白模」一起出现在场景格面板的切换里):剧本 / 分镜从连进来的文档、便签接,
    #: 搭出的场景落进这一格(有场景的格子换成新搭的,旧的还在「3D 场景」里)。它交出的是一个场景,文字是参数不是原料
    #: (boards.transforms 的判法),所以不挂在文档、便签上。
    "scene_from_text": {
        "external": False,
        "surfaces": ["workflow", "board"],
        "board_outputs": ["scene_id"],
        "board_group": "scene", "board_description": "wfNode_scene_from_text_board",
        "category": "wfCat_3d",
        "label": "wfNode_scene_from_text",
        "description": "wfNode_scene_from_text_desc",
        "config": {
            "text": {"type": "template", "required": True, "description": "wfNode_scene_from_text_text"},
            #: 一格挑模型(跨连接列,值里带着连接)—— 和「让 AI 写」同一份清单,不是「先挑连接再挑模型」两格。
            "model": {"type": "string", "options_from": "automation_chat_models", "description": "wfNode_scene_from_text_model"},
            "max_shots": {"type": "number", "default": 6, "description": "wfNode_scene_from_text_max_shots"},
            "shot_seconds": {"advanced": True, "type": "number", "default": 5, "description": "wfNode_scene_from_text_shot_seconds"},
            "aspect": {"type": "string", "default": "16:9", "options": ["16:9", "9:16", "1:1"], "description": "wfNode_scene_from_text_aspect"},
            "name": {"advanced": True, "type": "template", "description": "wfNode_scene_from_text_name"},
        },
        "outputs": ["scene_id", "shot_ids", "shot_count", "name"],
        "output_types": {"scene_id": "scene", "shot_ids": "json", "shot_count": "number", "name": "text"},
    },
    #: 不单独上画板:画板上渲白模是 **3D 场景格自己会做的事**(内置产出者 `scene_render`,见
    #: boards.producers),跑的是这同一个执行器、读的是这同一份字段声明 —— 此前一格工具格引用一格场景格,
    #: 同一件事分成两半摆在桌上。
    "scene_render": {
        "external": False,
        "surfaces": ["workflow"],
        "output_media": {"first_frame_asset_id": "image", "last_frame_asset_id": "image", "video_asset_id": "video"},
        "category": "wfCat_3d",
        "label": "wfNode_scene_render",
        "description": "wfNode_scene_render_desc",
        "config": {
            "scene_id": {"type": "template", "required": True, "options_from": "scenes",
                         "description": "wfNode_scene_render_scene_id"},
            #: 挑的是**这个场景的**镜头:换场景就换了一整套镜头 id(depends_on 清掉旧值、把场景带给选项来源)。
            #: 留空 = 场景只有一个镜头时用它 —— 运行时同一条规矩(scenes.render_shot_references),
            #: 所以不必替人把那唯一的一项写进配置;有好几个时不猜,报出来让人挑。
            "shot_id": {"type": "template", "depends_on": "scene_id", "options_from": "scene_shots",
                        "sole_option_default": True, "description": "wfNode_scene_render_shot_id"},
            #: 允许手填:整片流程里"这一镜要不要运镜视频"是逐镜决定的,值来自上游(`{{…}}`)。
            "render": {
                "type": "string", "default": "stills", "options": list(REFERENCE_RENDERS),
                "allow_custom": True, "description": "wfNode_scene_render_render",
            },
            "project_id": {"advanced": True, "type": "template", "options_from": "projects", "description": "wfNode_scene_render_project_id"},
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
        "surfaces": ["workflow", "board"],
        "board_outputs": ["vocals_asset_id", "background_asset_id"],
        "output_media": {"vocals_asset_id": "audio", "background_asset_id": "audio"},
        "board_group": "audio", "board_description": "wfNode_separate_audio_board",
        "category": "wfCat_audio",
        "label": "wfNode_separate_audio",
        "description": "wfNode_separate_audio_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": ["audio", "video"],
                         "description": "wfNode_separate_audio_asset_id"},
            # auto = 用现在跑得起来的那个。点名一个引擎是给"装了好几个"的人用的。
            # **选项从注册表读** —— 在这里再写一遍引擎名,加一个引擎就得改两处,
            # 漏改的那处表现为"装好了却选不到"。
            "engine": {
                "type": "string",
                #: 提供方(ADR 0032):内置引擎、配好的分离插件;留空 = 按运行者的默认。
                "description": "wfNode_separate_audio_engine",
                "options_from": "providers.audio_separation",
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
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_id"],
        #: 进什么出什么:视频进视频出(画面原样、只换声音),音频进音频出。此前声明成只出音频,
        #: 而整理模板正是拿它的产出(一段视频)放上视频轨。两种都列上;画板上说不清是哪一种时按
        #: board_group 画(它首先是一个音频工具,格子按音频画,见 boards.transforms.output_kinds)。
        "output_media": {"asset_id": ["audio", "video"]},
        "board_group": "audio", "board_description": "wfNode_denoise_audio_board",
        "category": "wfCat_audio",
        "label": "wfNode_denoise_audio",
        "description": "wfNode_denoise_audio_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": ["audio", "video"],
                         "description": "wfNode_denoise_audio_asset_id"},
            # 选项从注册表读(同分离节点)。auto = 内置的那个,它不会顺手去掉音乐。
            "engine": {
                "type": "string",
                #: 提供方(ADR 0032):内置引擎、配好的降噪插件;留空 = 按运行者的默认(不动配乐的第一个)。
                "description": "wfNode_denoise_audio_engine",
                "options_from": "providers.audio_denoise",
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
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences", "description": "wfNode_generate_subtitles_sequence_id"},
            "segments": {"type": "template", "required": True, "description": "wfNode_generate_subtitles_segments"},
            "texts": {"type": "template", "description": "wfNode_generate_subtitles_texts"},
            "keep_original": {
                "type": "string",
                "default": "no",
                "options": ["yes", "no"],
                "description": "wfNode_generate_subtitles_keep_original",
            },
            "offset": {"advanced": True, "type": "number", "description": "wfNode_generate_subtitles_offset"},
            #: 段落是哪个片段的素材转出来的:给了就按片段的入点和倍速映射到时间线(offset 不再用)。
            "clip_id": {"advanced": True, "type": "template", "description": "wfNode_generate_subtitles_clip_id"},
            #: 字幕最晚到时间线上的第几秒(一般接上游那一段的 timeline_end):超出的那一截裁掉、整条落在它之后的不上屏 ——
            #: 素材比计划短时,字幕不会盖到下一段上。
            "until": {"advanced": True, "type": "number", "description": "wfNode_generate_subtitles_until"},
            "track_id": {"advanced": True, "type": "template", "depends_on": "sequence_id", "options_from": "sequence_tracks",
                         "description": "wfNode_generate_subtitles_track_id"},
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
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences", "description": "wfNode_dub_subtitles_sequence_id"},
            #: 同上:字幕条属于上面那条时间线,换了时间线就清掉。
            "clip_ids": {"type": "template", "required": True, "depends_on": "sequence_id",
                         "description": "wfNode_dub_subtitles_clip_ids"},
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
                "default": "builtin:clone",
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
        "outputs": ["track_id", "done", "failed", "original_audio", "original_audio_note", "overlaps", "overlap_seconds",
                    "overlap_note"],
        "output_labels": {
            "original_audio": "wfOut_original_audio",
            "original_audio_note": "wfOut_original_audio_note",
            "overlaps": "wfOut_overlaps",
            "overlap_seconds": "wfOut_overlap_seconds",
            "overlap_note": "wfOut_overlap_note",
        },
        "output_types": {"done": "number", "failed": "number", "overlaps": "number", "overlap_seconds": "number"},
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
            "max_items": {"advanced": True, "type": "number", "description": "wfNode_loop_foreach_max_items"},
            "on_item_error": {
                "advanced": True,
                "type": "string",
                "default": "stop",
                "options": ["stop", "skip"],
                "description": "wfNode_loop_foreach_on_item_error",
            },
        },
        "outputs": ["results", "count", "dropped", "failed", "failure_note"],
        "output_types": {"failed": "json", "failure_note": "text"},
        "output_labels": {"failed": "wfOut_loop_failed"},
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
    #: 资产库(ADR 0027 阶段 4):取一个人物 / 场景 / 道具交给下游,或把画好的图存回去。「从主题到完整视频」
    #: 先按名字取(取不到 found = 0 再去画),画完存 —— 下一部片子里同一个角色是同一张脸。
    "entity_get": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_entity_get",
        "description": "wfNode_entity_get_desc",
        "config": {
            #: 点名和按名字找**恰好用一种**(执行体两样都没有就报 wfErr_entityGetNeedsTarget)。写成 one_of,
            #: 两样都空在运行前就拦住 —— 数字人出镜带货里「挑一位主播」空着的话,此前要等脚本那次对话计完费才失败。
            "entity_id": {"type": "template", "one_of": "target", "options_from": "entities",
                          "description": "wfNode_entity_get_entity_id"},
            "kind": {"type": "string", "options": ["character", "location", "prop"], "description": "wfNode_entity_get_kind"},
            "name": {"type": "template", "one_of": "target", "description": "wfNode_entity_get_name"},
            "limit": {"advanced": True, "type": "number", "description": "wfNode_entity_get_limit"},
        },
        "outputs": ["entity_id", "found", "name", "description", "prompt", "asset_ids", "asset_id", "voice_engine", "voice_id"],
        "output_types": {"found": "number", "name": "text", "description": "text", "prompt": "text"},
    },
    "entity_list": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_entity_list",
        "description": "wfNode_entity_list_desc",
        "config": {
            "kind": {"type": "string", "options": ["character", "location", "prop"], "description": "wfNode_entity_list_kind"},
            "tag": {"type": "template", "description": "wfNode_entity_list_tag"},
            "query": {"type": "template", "description": "wfNode_entity_list_query"},
            "limit": {"advanced": True, "type": "number", "description": "wfNode_entity_list_limit"},
        },
        "outputs": ["entities", "count", "text"],
        "output_types": {"entities": "json", "count": "number", "text": "text"},
    },
    "entity_save": {
        "external": False,
        "category": "wfCat_asset",
        "label": "wfNode_entity_save",
        "description": "wfNode_entity_save_desc",
        "config": {
            "kind": {"type": "string", "required": True, "options": ["character", "location", "prop"], "description": "wfNode_entity_save_kind"},
            "name": {"type": "template", "required": True, "description": "wfNode_entity_save_name"},
            "prompt": {"type": "template", "description": "wfNode_entity_save_prompt"},
            "description": {"type": "template", "description": "wfNode_entity_save_description"},
            "asset_ids": {"type": "template", "description": "wfNode_entity_save_asset_ids", "media": ["image", "video"]},
            "role": {"type": "string", "options_from": "entity_roles", "depends_on": "kind", "description": "wfNode_entity_save_role"},
            "tags": {"advanced": True, "type": "template", "description": "wfNode_entity_save_tags"},
            "if_exists": {"advanced": True, "type": "string", "default": "merge", "options": ["merge", "new"], "description": "wfNode_entity_save_if_exists"},
        },
        "outputs": ["entity_id", "created", "added", "name"],
        "output_types": {"created": "number", "added": "number", "name": "text"},
    },
    #: 资产格的两项能力(ADR 0027 §3「画板」):拿这个资产现有的参考图再画几张「同一个」,画成的按角度挂回去。
    #: 画板上宿主就是那一格资产(`entity_id` 字段装的是资产,boards.tools 的 entity 接口),产出新建在右边;
    #: 工作流里点名一个资产,或接上游「取资产」「存成资产」给的 id。每一张是一次付费的生成。
    "entity_angles": {
        "external": False,
        "effects": "paid",
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_ids"],
        "output_media": {"asset_ids": "image"},
        "board_group": "entity", "board_description": "wfNode_entity_angles_board",
        "category": "wfCat_ai",
        "label": "wfNode_entity_angles",
        "description": "wfNode_entity_angles_desc",
        "config": {
            "entity_id": {"type": "template", "required": True, "data_type": "entity", "options_from": "entities",
                          "description": "wfNode_entity_angles_entity_id"},
            "model": {"type": "string", "options_from": "reference_image_models", "description": "wfNode_entity_model"},
            "scope": {"type": "string", "default": "missing", "options": ["missing", "all"],
                      "description": "wfNode_entity_angles_scope"},
        },
        "outputs": ["asset_ids", "asset_id", "entity_id", "added", "failed"],
        "output_types": {"asset_ids": "asset", "added": "number", "failed": "number"},
    },
    "entity_expressions": {
        "external": False,
        "effects": "paid",
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_ids"],
        "output_media": {"asset_ids": "image"},
        "board_group": "entity", "board_description": "wfNode_entity_expressions_board",
        "category": "wfCat_ai",
        "label": "wfNode_entity_expressions",
        "description": "wfNode_entity_expressions_desc",
        "config": {
            "entity_id": {"type": "template", "required": True, "data_type": "entity",
                          "options_from": "entities.character", "description": "wfNode_entity_expressions_entity_id"},
            "model": {"type": "string", "options_from": "reference_image_models", "description": "wfNode_entity_model"},
            "expressions": {"type": "template", "description": "wfNode_entity_expressions_expressions"},
        },
        "outputs": ["asset_ids", "asset_id", "entity_id", "added", "failed"],
        "output_types": {"asset_ids": "asset", "added": "number", "failed": "number"},
    },
    #: 数字人(ADR 0028 §4):配音 → 说话照片 / 改口型。画板上分别是人物资产格、图片格、视频格的能力。每一次都是付费生成。
    "entity_speak": {
        "external": False,
        "effects": "paid",
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_id", "audio_asset_id"],
        "output_media": {"asset_id": "video", "audio_asset_id": "audio"},
        "board_group": "entity", "board_description": "wfNode_entity_speak_board",
        "category": "wfCat_ai",
        "label": "wfNode_entity_speak",
        "description": "wfNode_entity_speak_desc",
        "config": {
            "entity_id": {"type": "template", "required": True, "data_type": "entity", "options_from": "entities.character",
                          "description": "wfNode_entity_speak_entity_id"},
            "text": {"type": "template", "required": True, "description": "wfNode_talking_text"},
            "model": {"type": "string", "options_from": "speech_video_models", "description": "wfNode_talking_model"},
            "resolution": {"advanced": True, "type": "string", "depends_on": "model", "options_from": "speech_video_resolutions",
                           "description": "wfNode_talking_resolution"},
        },
        "outputs": ["asset_id", "asset_ids", "audio_asset_id"],
    },
    "image_speak": {
        "external": False,
        "effects": "paid",
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_id", "audio_asset_id"],
        "output_media": {"asset_id": "video", "audio_asset_id": "audio"},
        "board_group": "image", "board_description": "wfNode_image_speak_board",
        "category": "wfCat_ai",
        "label": "wfNode_image_speak",
        "description": "wfNode_image_speak_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": "image", "description": "wfNode_image_speak_asset_id"},
            #: 音频接上游的(长稿分段配好的一段、画板上连进来的音频格)—— 参数,不是宿主(和对口型同一条)。
            "audio_asset_id": {"type": "template", "media": "audio", "board_host": False,
                                "description": "wfNode_image_speak_audio"},
            "text": {"type": "template", "description": "wfNode_image_speak_text"},
            "engine": {"type": "string", "default": "builtin:clone", "options_from": "speech_engines", "description": "wfNode_speech_engine"},
            "voice": {"type": "string", "depends_on": "engine", "options_from": "speech_voices", "description": "wfNode_speech_voice"},
            "model": {"type": "string", "options_from": "speech_video_models", "description": "wfNode_talking_model"},
            "resolution": {"advanced": True, "type": "string", "depends_on": "model", "options_from": "speech_video_resolutions",
                           "description": "wfNode_talking_resolution"},
            "consent": {"type": "string", "required": True, "options": ["yes"], "description": "wfNode_talking_consent"},
        },
        "outputs": ["asset_id", "asset_ids", "audio_asset_id"],
    },
    "video_lipsync": {
        "external": False,
        "effects": "paid",
        "surfaces": ["workflow", "board"],
        "board_outputs": ["asset_id", "audio_asset_id"],
        "output_media": {"asset_id": "video", "audio_asset_id": "audio"},
        "board_group": "video", "board_description": "wfNode_video_lipsync_board",
        "category": "wfCat_ai",
        "label": "wfNode_video_lipsync",
        "description": "wfNode_video_lipsync_desc",
        "config": {
            "asset_id": {"type": "template", "required": True, "media": "video", "description": "wfNode_video_lipsync_asset_id"},
            #: 音频从上游的音频格接 —— 它是参数,不是宿主:这一项只挂在视频格上(boards.transforms 的 `board_host`)。
            "audio_asset_id": {"type": "template", "media": "audio", "board_host": False,
                                "description": "wfNode_video_lipsync_audio"},
            "text": {"type": "template", "description": "wfNode_video_lipsync_text"},
            "engine": {"type": "string", "default": "builtin:clone", "options_from": "speech_engines", "description": "wfNode_speech_engine"},
            "voice": {"type": "string", "depends_on": "engine", "options_from": "speech_voices", "description": "wfNode_speech_voice"},
            "model": {"type": "string", "options_from": "lipsync_models", "description": "wfNode_talking_model"},
            "consent": {"type": "string", "required": True, "options": ["yes"], "description": "wfNode_talking_consent"},
        },
        "outputs": ["asset_id", "asset_ids", "audio_asset_id"],
    },
    "dub_lipsync": {
        "external": False,
        #: 每一块有配音的原片是一次付费的改口型。
        "effects": "paid",
        "category": "wfCat_ai",
        "label": "wfNode_dub_lipsync",
        "description": "wfNode_dub_lipsync_desc",
        "config": {
            "sequence_id": {"type": "template", "required": True, "options_from": "sequences", "description": "wfNode_dub_lipsync_sequence_id"},
            #: 同上:原片那一段属于上面那条时间线,换了时间线就清掉(否则跑起来是 wfErr_dubLipsyncNeedsClip)。
            "clip_id": {"type": "template", "required": True, "depends_on": "sequence_id",
                        "description": "wfNode_dub_lipsync_clip_id"},
            "track_id": {"type": "template", "required": True, "depends_on": "sequence_id", "options_from": "sequence_tracks",
                         "description": "wfNode_dub_lipsync_track_id"},
            "model": {"type": "string", "options_from": "lipsync_models", "description": "wfNode_talking_model"},
            "consent": {"type": "string", "required": True, "options": ["yes"], "description": "wfNode_talking_consent"},
        },
        "outputs": ["asset_id", "clip_id", "track_id", "chunk_count", "generated_count", "reused_count"],
        "output_types": {"chunk_count": "number", "generated_count": "number", "reused_count": "number"},
    },
    "talking_segments": {
        "external": False,
        #: 逐句配音:走 TTS,云端引擎按字计费。
        "effects": "paid",
        "category": "wfCat_ai",
        "label": "wfNode_talking_segments",
        "description": "wfNode_talking_segments_desc",
        "config": {
            "text": {"type": "template", "required": True, "description": "wfNode_talking_segments_text"},
            "engine": {"type": "string", "default": "builtin:clone", "options_from": "speech_engines", "description": "wfNode_speech_engine"},
            #: 必填,和「语音合成」同一条:执行体空着就报 wfErr_talkingNeedsVoice —— 声明成必填,运行前就拦住。
            "voice": {"type": "string", "required": True, "depends_on": "engine", "options_from": "speech_voices",
                      "description": "wfNode_speech_voice"},
            "model": {"type": "string", "options_from": "speech_video_models", "description": "wfNode_talking_segments_model"},
            "max_seconds": {"advanced": True, "type": "number", "description": "wfNode_talking_segments_max_seconds"},
        },
        #: `model`:按哪个说话照片模型的上限切的段 —— 下游「让它说话」的模型接它,两步用的是同一个。
        "outputs": ["segments", "cues", "count", "duration", "model"],
        "output_types": {"segments": "json", "cues": "json", "count": "number", "duration": "number"},
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
            "project_id": {"type": "template", "options_from": "projects", "description": "wfNode_asset_update_project_id"},
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
            "project_id": {"advanced": True, "type": "template", "options_from": "projects",
                           "description": "wfNode_project_sequence_create_project_id"},
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
        # 一张动态映射同时扮演两侧契约:左边逐项接收要交付的值，右边逐项暴露给下游。
        # 路径写的是执行上下文里的真实位置，画布和数据边都不需要认识 output 节点。
        "port_maps": {"values": {"input": "values", "output": "output"}},
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
            "session_mode": {
                "type": "string", "options": ["ephemeral", "named", "pool"], "default": "ephemeral",
                "description": "wfNode_browser_open_session_mode",
            },
            #: 只在对应的模式下出现、也只在那时必填(active_when + required,表单和运行前校验读同一条声明)。
            "session_name": {
                "type": "template", "required": True, "active_when": {"session_mode": "named"},
                "description": "wfNode_browser_open_session_name",
            },
            "profile_id": {
                "type": "string", "required": True, "active_when": {"session_mode": "pool"},
                "label": "wfField_browser_profile",
                "description": "wfNode_browser_open_profile_id", "options_from": "browser_profiles",
            },
            "allow_error_page": {
                "advanced": True, "type": "string", "options": ["false", "true"], "default": "false",
                "description": "wfNode_browser_allow_error_page",
            },
        },
        "outputs": ["session", "notice", "status"],
        "output_labels": {"notice": "wfOut_browser_open_notice", "status": "wfOut_browser_http_status"},
    },
    "browser_navigate": {
        "external": True,
        "category": "wfCat_browser",
        "label": "wfNode_browser_navigate",
        "description": "wfNode_browser_navigate_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_navigate_session"},
            "url": {"type": "template", "required": True, "description": "wfNode_browser_navigate_url"},
            "allow_error_page": {
                "advanced": True, "type": "string", "options": ["false", "true"], "default": "false",
                "description": "wfNode_browser_allow_error_page",
            },
        },
        #: 状态码见「允许错误页」;打开的地址本身是个文件时(PDF、mp4 直链……)浏览器会下载它:不弹框,直接进
        #: 素材库,交出素材 id(没下载是空串)。
        "outputs": ["session", "status", "asset_id"],
        "output_labels": {"status": "wfOut_browser_http_status", "asset_id": "wfOut_browser_downloaded_asset"},
    },
    "browser_click": {
        "external": True,
        "category": "wfCat_browser",
        "label": "wfNode_browser_click",
        "description": "wfNode_browser_click_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_click_session"},
            #: 按选择器还是按文字点,恰好一个(one_of):两个都填时执行器只认选择器,文字那格静悄悄地不起作用。
            "selector": {"type": "template", "one_of": "target", "description": "wfNode_browser_click_selector"},
            "text": {"type": "template", "one_of": "target", "description": "wfNode_browser_click_text"},
            "exact": {"advanced": True, "type": "string", "options": ["false", "true"], "description": "wfNode_browser_click_exact"},
            "wait_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_click_wait_ms"},
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
        },
        #: 点的是下载链接时,文件不弹框、直接进素材库,交出素材 id(没下载就是空串)。
        "outputs": ["session", "asset_id"],
        "output_labels": {"asset_id": "wfOut_browser_downloaded_asset"},
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
            "wait_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_input_wait_ms"},
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
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
            #: 两样都给时上传会报错(不替人挑,见 host_files.upload_source),所以没有「引用在前、兜底在后」。
            "asset_id": {"type": "template", "one_of": "source", "one_of_strict": True,
                         "description": "wfNode_browser_upload_asset_id"},
            "file_path": {"type": "template", "one_of": "source", "one_of_strict": True,
                          "description": "wfNode_browser_upload_file_path"},
            "timeout_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_upload_timeout_ms"},
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
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
            "allow_missing": {
                "advanced": True, "type": "string", "options": ["false", "true"],
                "description": "wfNode_browser_extract_allow_missing",
            },
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
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
            #: 等什么,三选一(one_of),三个都在第一屏:此前网址和文字收在高级里,只看第一屏的人以为只能等元素。
            "selector": {"type": "template", "one_of": "condition", "description": "wfNode_browser_wait_selector"},
            "url_contains": {"type": "template", "one_of": "condition", "description": "wfNode_browser_wait_url_contains"},
            "text": {"type": "template", "one_of": "condition", "description": "wfNode_browser_wait_text"},
            "gone": {"advanced": True, "type": "string", "options": ["false", "true"], "description": "wfNode_browser_wait_gone"},
            "timeout_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_wait_timeout_ms"},
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
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
            "allow_missing": {
                "advanced": True, "type": "string", "options": ["false", "true"],
                "description": "wfNode_browser_scroll_allow_missing",
            },
            "frame": {"advanced": True, "type": "template", "description": "wfNode_browser_frame"},
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
            #: 脚本本身**不插值**(code 字段一律不插,见 binding.interpolate_node_config);要用上游的值放进 input,
            #: 脚本里按 `input.名字` 读 —— 值作为 JSON 数据交进去,拼不进代码。
            "expression": {"type": "code", "required": True, "description": "wfNode_browser_evaluate_expression"},
            "input": {"type": "object", "description": "wfNode_browser_evaluate_input"},
            # 长读脚本(分页拉评论这种)声明自己的预算;缺省 20s,上限三分钟。
            "timeout_ms": {"advanced": True, "type": "number", "description": "wfNode_browser_evaluate_timeout"},
        },
        "outputs": ["session", "value"],
    },
    #: 会话里开着几个页面时(新窗口、target=_blank 会进会话的页面列表并自动切过去):切到某一页,或关掉
    #: 当前页。单独一个节点而不是并进「打开网址」:那个节点的意思是「当前页去这个地址」,再塞进「换一页」
    #: 「关一页」,同一个表单就有三种互不相干的填法,输出也说不清是哪一页的。
    "browser_page": {
        "external": True,
        "category": "wfCat_browser",
        "label": "wfNode_browser_page",
        "description": "wfNode_browser_page_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_page_session"},
            "operation": {
                "type": "string", "options": ["switch", "close"], "default": "switch",
                "label": "wfField_browser_page_operation", "description": "wfNode_browser_page_operation",
            },
            "by": {
                "type": "string", "options": ["index", "title", "url"], "default": "index",
                "active_when": {"operation": "switch"},
                "label": "wfField_browser_page_by", "description": "wfNode_browser_page_by",
            },
            "value": {
                "type": "template", "required": True, "active_when": {"operation": "switch"},
                "description": "wfNode_browser_page_value",
            },
        },
        "outputs": ["session", "url", "title", "count"],
        "output_labels": {
            "url": "wfOut_browser_page_url", "title": "wfOut_browser_page_title", "count": "wfOut_browser_page_count",
        },
    },
    #: 截这一页存进素材库。截图本身和浏览器会话顶栏的「截屏」是同一份实现(electron/publish/pageCapture);
    #: 框选要人拖,节点里换成「某个元素」。
    "browser_screenshot": {
        "external": True,
        "category": "wfCat_browser",
        "label": "wfNode_browser_screenshot",
        "description": "wfNode_browser_screenshot_desc",
        "config": {
            "session": {"type": "string", "required": True, "description": "wfNode_browser_screenshot_session"},
            "mode": {
                "type": "string", "options": ["visible", "full", "element"], "default": "visible",
                "description": "wfNode_browser_screenshot_mode",
            },
            "selector": {
                "type": "template", "required": True, "active_when": {"mode": "element"},
                "description": "wfNode_browser_screenshot_selector",
            },
            "name": {"advanced": True, "type": "template", "description": "wfNode_browser_screenshot_name"},
            #: 截会话里的哪一页(新窗口会进会话的页面列表):不在前台、甚至从没显示过的页面也截得到。
            "page_by": {
                "advanced": True, "type": "string", "options": ["current", "index", "title", "url"], "default": "current",
                "label": "wfField_browser_screenshot_page_by", "description": "wfNode_browser_screenshot_page_by",
            },
            "page_value": {
                "advanced": True, "type": "template", "required": True,
                "active_when": {"page_by": ["index", "title", "url"]},
                "label": "wfField_browser_screenshot_page_value", "description": "wfNode_browser_page_value",
            },
            "wait_ms": {
                "advanced": True, "type": "number", "active_when": {"mode": "element"},
                "description": "wfNode_browser_screenshot_wait_ms",
            },
        },
        "outputs": ["session", "asset_id"],
        "output_labels": {"asset_id": "wfOut_browser_screenshot_asset"},
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
