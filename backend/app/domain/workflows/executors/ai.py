"""AI 文本类节点:经自动化执行面做单次补全(不产生子 job、不开放智能体工具)。"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import SchemaError, ValidationError, validate as validate_json_schema
from jsonschema.validators import validator_for
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.core.usage_scope import workspace_scope
from app.domain.ai_chat import AiChatError, chat, response_format_tier, target_for
from app.domain.usage import billable, once
from app.domain.providers import require_connection
from app.domain.workflows import WorkflowDomainError
from app.domain.jobs import current_actor
from app.domain.workflows.executors import register
from app.domain.workflows.executors.common import text_lines

LLM_TIMEOUT_SECONDS = 120

# 供应商偶发瞬断(Server disconnected / 连接或读超时 / 429 限流 / 5xx 过载)是常态,让整条工作流
# 一次就挂太脆。重试与退避统一在 domain/ai_retry 的传输层做,**所有 AI 出站调用共用**;
# 这里只保留「读设置」这一步,因为工作流执行器手上正好有 db 会话。
DEFAULT_MAX_RETRIES = 3
MAX_RETRIES_CAP = 10


def configured_max_retries(db: Session) -> int:
    """读取用户设置的「供应商瞬断最大重试次数」;缺省 3,夹在 0..10。"""
    from app.db.models import AiRuntimeConfig

    row = db.get(AiRuntimeConfig, "default")
    value = row.max_retries if row is not None else DEFAULT_MAX_RETRIES
    return max(0, min(int(value), MAX_RETRIES_CAP))

# 生成风格预设 → temperature(替代让用户填裸数值)。默认均衡。
_LLM_PRESET_TEMPS = {"precise": 0.1, "balanced": 0.4, "creative": 0.9}


def _float_config(config: dict[str, Any], key: str, *, min_value: float | None = None, max_value: float | None = None) -> float | None:
    raw = config.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_mustBeNumber", params={"field": key}) from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError("wfErr_belowMin", params={"field": key, "min": f"{min_value:g}"})
    if max_value is not None and value > max_value:
        raise WorkflowDomainError("wfErr_aboveMax", params={"field": key, "max": f"{max_value:g}"})
    return value


def _int_config(config: dict[str, Any], key: str, *, min_value: int | None = None) -> int | None:
    raw = config.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_mustBeInteger", params={"field": key}) from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError("wfErr_belowMin", params={"field": key, "min": min_value})
    return value


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    raw = config.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off", "否"}


def _stop_sequences(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [line.strip() for line in str(value).splitlines() if line.strip()]
    return items or None


def _response_format(config: dict[str, Any]) -> dict[str, Any] | None:
    mode = str(config.get("response_format") or "text")
    if mode == "text":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    if mode != "json_schema":
        raise WorkflowDomainError("wfErr_responseFormat")
    schema = config.get("json_schema")
    if not isinstance(schema, dict) or not schema:
        raise WorkflowDomainError("wfErr_schemaEmpty")
    name = str(config.get("json_schema_name") or schema.get("title") or "workflow_output").strip() or "workflow_output"
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": _bool_config(config, "json_schema_strict", True),
        },
    }


#: 去掉 ```json 围栏之后,正文的第一个字符。用来区分两种完全不同的失败。
_FENCE = ("```json", "```JSON", "```")


def _unfenced(text: str) -> str:
    body = text.strip()
    for fence in _FENCE:
        if body.startswith(fence):
            body = body[len(fence):].lstrip()
            break
    return body


def _parse_json_response(text: str) -> Any:
    """Parse one JSON value even when a text-only model wraps it in prose.

    Providers that reject ``response_format`` are retried in plain-text mode by
    the shared chat gateway. Those models commonly return a Markdown fence or a
    short explanation around an otherwise valid value. ``raw_decode`` keeps the
    fallback structural (and safe for nested JSON) without trying to repair a
    truncated or malformed answer.

    **但捞回来的必须是"被散文包着的那个值",不能是"一个坏结构里的碎片"。**

    此前这里对所有失败一视同仁:从头扫,遇到第一个能 `raw_decode` 成功的 `[` 或 `{` 就返回。
    模型返回一个**自身格式错误**的大对象时(实测:它把 `continuity_rules` 的数组用引号包成了
    字符串,里面的引号又没转义),从 0 开始解析必然失败,于是这个兜底往下扫,捞到了那个数组 ——
    把答案里的一个字段当成整个答案交了出去。

    后果是**报错指向了完全错误的地方**:下游 schema 校验说「这个 list 不是 object」,用户看到的
    是一长串连续性规则加一句 is not of type 'object',而真正的毛病是"这个 JSON 根本没闭合"。
    比直接报解析失败糟得多 —— 后者至少是真话。

    判据:正文(去掉围栏后)**以 `{` 或 `[` 开头**,说明模型本来就在返回纯 JSON,那它没解析成功
    就是坏的,照实报。只有正文不以括号开头(真的是散文里裹着一个值)才往下扫。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as strict_error:
        decoder = json.JSONDecoder()
        body = _unfenced(text)
        if body[:1] in ("{", "["):
            # 它本来就在返回 JSON(可能裹着 ```json 围栏)。从**正文开头**解一次:
            # 成功就是围栏的事,失败就是这份 JSON 自己坏了 —— 后者绝不往下捞碎片,
            # 捞出来的只会是答案里的一个字段,而错误会因此指向完全无关的地方。
            try:
                value, _end = decoder.raw_decode(body, 0)
            except json.JSONDecodeError:
                raise strict_error from None
            return value
        for index, character in enumerate(text):
            if character not in "[{":
                continue
            try:
                value, _end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            return value
        raise strict_error


def _schema_for_prompt(config: dict[str, Any]) -> str:
    """这一轮要贴给模型看的 JSON 约定;不要 JSON 就返回空串。

    两件事都在这里办:

    1. **把 Schema 正文给它看。** 它此前只进 `payload.response_format`,而那一项能不能生效完全
       看供应商 —— 不生效时模型收到的是一句"要符合 Schema",而那个 Schema 它从来没见过。
    2. **让请求里一定出现 "json" 这个词。** DeepSeek 在 `response_format: json_object` 下硬性
       要求提示词里带这个词,否则直接 400:`Prompt must contain the word 'json' in some form`。
       没有 Schema 的 json_object 节点此前什么都不贴,于是那条请求必然失败 —— 用户的任务记录里
       就躺着这一条。所以没有 Schema 时也要贴一句短的。

    开头带上网关那条兼容标记:降级路径(`ai_chat._downgrade_response_format_payload`)见到它就
    不再另贴一份契约,免得同一份 Schema 在一次请求里出现两遍。
    """
    from app.domain.ai_chat import JSON_CONTRACT_MARKER

    mode = str(config.get("response_format") or "text")
    if mode not in {"json_schema", "json_object"}:
        return ""
    common = (
        "不要 Markdown 围栏、不要任何解释文字,不要把数组或对象包进字符串里,字符串内部的引号要转义。"
    )
    schema = config.get("json_schema")
    if not isinstance(schema, dict) or not schema:
        # json_object 但没给 Schema:形状约束不了,但"必须是一个 JSON 对象"仍要说,
        # 而且这句话本身就带上了那个供应商要找的 "json"。
        return f"{JSON_CONTRACT_MARKER}\n你这一轮的回答必须是**一个** JSON 对象(JSON object)。{common}"
    body = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{JSON_CONTRACT_MARKER}\n"
        f"你这一轮的回答必须是**一个**符合下面这份 JSON Schema 的 JSON 对象。{common}\n{body}"
    )


def _request_payload(config: dict[str, Any], model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    temperature = _float_config(config, "temperature", min_value=0, max_value=2)
    if temperature is None:
        temperature = _LLM_PRESET_TEMPS.get(str(config.get("preset") or "balanced"), 0.4)
    payload["temperature"] = temperature

    numeric_fields = {
        "top_p": (0.0, 1.0),
        "frequency_penalty": (-2.0, 2.0),
        "presence_penalty": (-2.0, 2.0),
    }
    for key, (min_value, max_value) in numeric_fields.items():
        value = _float_config(config, key, min_value=min_value, max_value=max_value)
        if value is not None:
            payload[key] = value
    max_tokens = _int_config(config, "max_tokens", min_value=1)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    seed = _int_config(config, "seed")
    if seed is not None:
        payload["seed"] = seed
    stop = _stop_sequences(config.get("stop"))
    if stop is not None:
        payload["stop"] = stop
    response_format = _response_format(config)
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


def _honour_structured_output(payload: dict[str, Any], supported: bool | None) -> dict[str, Any]:
    """已经查证过不支持 json_schema 的端点,就别把那一档发出去。

    `None` 是**不知道**,照发 —— 网关那条降级链(json_schema → json_object → 纯文本)本来就是
    对的,只是白花一个往返。而已知不支持时那个往返是**必然**白花的:DeepSeek 这类端点会 400,
    然后我们降一档重来。直接降到 json_object,少一次请求,也少一次"用户看不懂的 400"。

    **不降到纯文本**:json_object 至少保证语法合法,而 Schema 正文已经在消息里了
    (见 `_schema_for_prompt`),形状仍然管得住。
    """
    if supported is not False:
        return payload
    current = payload.get("response_format")
    if isinstance(current, dict) and current.get("type") == "json_schema":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _enforced_locally(config: dict[str, Any], used_tier: str) -> bool:
    """这次调用里,那份 Schema 到底**有没有**被供应商当成硬约束。

    配置上写着 json_schema 不等于它生效了:端点可能已查证不支持(上面那次预降级)、
    可能当场 400、也可能在这一档下返回空正文(见 domain/ai_chat 的降级链)。
    三种情况下模型都只是"看过一份贴在提示词里的 Schema",没有任何东西强制它遵守。

    这个区别要说出来,因为本地那次校验在两种完全不同的情况下会报**同一句话**:
    用户节点上明明写着 json_schema + strict,于是他以为是模型笨,而不是那份图纸从来没
    被强制执行过。
    """
    return str(config.get("response_format")) == "json_schema" and used_tier == "json_schema"


#: 校验不过时最多再让模型改几次。**1 就够**:这类错要么第二次就对(它拿到了具体哪一格错了),
#: 要么是提示词和 schema 本身打架(比如"每镜 2~3 秒"配上"总长 20 秒、约 9 镜"),再试十次一样。
#: 而每一次都是一次付费调用,所以不能为了"总有一次能过"无限试。
JSON_REPAIR_ATTEMPTS = 1


class _BadJson(Exception):
    """模型这次的回答不合格,以及**要怎么跟它说**。

    `feedback` 是原样发回给模型的那句话 —— 它必须说清楚哪一格错了,否则模型只能瞎改。
    """

    def __init__(
        self, key: str, reason: str, feedback: str, details: dict[str, Any], params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(reason)
        self.key = key
        self.reason = reason
        #: 给人看的那句话的参数(见 `key`);缺省只有原因本身。
        self.params = params if params is not None else {"reason": reason}
        self.feedback = feedback
        self.details = details


def _schema_failure(error: ValidationError) -> tuple[str, str]:
    """(给人看的原因, 发回给模型的话)。

    **带上出错的字段路径。** 此前只取 `exc.message`,于是界面上是一句「1 is less than the
    minimum of 2」——哪个字段、第几个镜头都不说,用户和我都得翻开原始返回自己数。
    `json_path` 本来就在异常身上(`$.shots[8].duration_seconds`),白扔了。
    """
    path = error.json_path if hasattr(error, "json_path") else "$"
    reason = f"{path}:{error.message}" if path and path != "$" else error.message
    return reason, f"{path} 不符合 Schema:{error.message}"


def _json_result(
    text: str, raw_text: str, config: dict[str, Any], model: str, *, used_tier: str = "json_schema"
) -> Any:
    """解析并校验这一次的回答;不合格就抛 `_BadJson`(带上要跟模型说的话)。

    `used_tier` 是这一轮**实际跑在**哪一档 —— 校验失败时要说清是「有硬约束却违反了」
    还是「本来就没有硬约束」,那是两件完全不同的事。
    """
    base = {
        "kind": "llm_json_response",
        "model": model,
        "response_format": str(config.get("response_format")),
        "raw_response": raw_text,
    }
    try:
        value = _parse_json_response(text)
    except json.JSONDecodeError as exc:
        raise _BadJson(
            "wfErr_llmNotJson",
            str(exc),
            f"你上一次的回答不是合法 JSON:{exc}。请只输出一个完整、可直接 json.loads 的对象,"
            "不要用 Markdown 围栏,不要把数组或对象包进字符串里,字符串内部的引号要转义。",
            {**base, "parse_error": str(exc)},
        ) from exc
    if str(config.get("response_format")) == "json_schema":
        try:
            validate_json_schema(instance=value, schema=config.get("json_schema"))
        except SchemaError:
            # schema 自己写错了 —— 不是模型的问题,重试没有意义,交给上层照实报。
            raise
        except ValidationError as exc:
            reason, feedback = _schema_failure(exc)
            enforced = _enforced_locally(config, used_tier)
            # **没有硬约束时换一句话**:用户节点上写着 json_schema + strict,答歪了会以为
            # 是模型笨。而真相是那份图纸从来没被这个端点强制执行过 —— 它只在提示词里
            # 露过一面。能动手的方向完全不同(换个端点 / 简化 Schema),所以要说出来。
            # 是另一个 key 而不是往 reason 后面拼一截:拼进去的那半句就只有一种语言了。
            raise _BadJson(
                "wfErr_jsonSchemaMismatch" if enforced else "wfErr_jsonSchemaMismatchUnenforced",
                reason,
                f"你上一次的回答不符合 JSON Schema:{feedback}。请只改这一处,其余内容原样保留,"
                "重新输出完整对象。",
                {**base, "response_format": "json_schema", "schema_error": reason,
                 "response_format_used": used_tier, "schema_enforced": enforced},
                {"reason": reason} if enforced else {"reason": reason, "tier": used_tier},
            ) from exc
    return value


@register("llm")
def llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = require_connection(db, config.get("profile_id"), user_id=current_actor(db), error=WorkflowDomainError)
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    prompt = str(config.get("prompt", ""))
    # 空提示词是最常见的一类 400(prompt 切了「引用」却没绑上游、或上游给了空):提前拦下,给准信。
    if not prompt.strip():
        raise WorkflowDomainError("wfErr_llmPromptEmpty")
    messages.append({"role": "user", "content": prompt})
    # **把 Schema 本身也给模型看。**
    #
    # 此前它只进 `payload.response_format`,而那一项能不能生效**完全看供应商**:DeepSeek 只支持
    # `{"type":"json_object"}`,根本没有 json_schema;不认这个参数的端点还会被网关逐级降级
    # (json_schema → json_object → 纯文本,见 domain/ai_chat)。于是在这些端点上,模型收到的是
    # 一句"只输出符合 JSON Schema 的对象"—— **而那个 Schema 它从来没见过**。
    #
    # 两次真实失败都出在这里:一次是某个字段超出了它看不见的取值范围,一次是整份 JSON 根本没闭合。
    # 对本来就支持结构化输出的端点,多这一段只是多几百 token,而且官方也建议照写;对不支持的,
    # 这是能不能用的分别。
    schema_text = _schema_for_prompt(config)
    if schema_text:
        messages.append({"role": "user", "content": schema_text})
    wants_json = str(config.get("response_format") or "text") in {"json_object", "json_schema"}
    try:
        target = target_for(db, profile, model=str(config.get("model") or ""), surface="automation")
        requested = _request_payload(config, target.model, messages)
        payload = _honour_structured_output(requested, target.structured_output)
        allow_response_format_fallback = "response_format" in payload
        # 这一轮**实际**跑在哪一档。预降级(上面那次)和运行中的两次降级都会改它 ——
        # 此前这个事实在任何地方都不存在:节点输出没有、失败详情里那个 response_format 取自
        # config(是**配置的**那一档)、账上也没有。降级成功时一切正常,只有模型在没有硬约束
        # 的情况下答歪了,用户才会看到一句 Schema 不符,然后以为是模型笨。
        used_tier = response_format_tier(payload)
        downgrades: list[dict[str, str]] = []

        def _note_downgrade(from_tier: str, to_tier: str, reason: str) -> None:
            nonlocal used_tier
            used_tier = to_tier
            downgrades.append({"from": from_tier, "to": to_tier, "reason": reason})
        # **schema 本身写错要在花钱之前就发现。** 它和"模型答得不对"是两回事:前者重试一百次也一样,
        # 而下面那个循环会为了让模型改对再调一次 —— 先在这里把坏 schema 挡掉,免得白花那一次。
        if str(config.get("response_format")) == "json_schema":
            schema = config.get("json_schema")
            try:
                validator_for(schema).check_schema(schema)
            except SchemaError as exc:
                raise WorkflowDomainError("wfErr_schemaInvalid", params={"reason": exc.message}) from exc
        with billable(
            db,
            capability="chat",
            operation="workflow_llm",
            idempotency_key=once("workflow_llm"),
            workspace_id=workflow.workspace_id,
            source_type="workflow",
            source_id=workflow.id,
        ) as call:
            turn = list(messages)
            bad: _BadJson | None = None
            # **不合格就把错误发回去,让它改。** 这类错模型一轮就能自纠(它拿到了具体哪一格错了),
            # 而此前一次不合格就让整条流程作废 —— 实测那次:67 秒、三次已经成功的付费调用,
            # 全废在 200 多个字段里的一个上。
            for attempt in range(JSON_REPAIR_ATTEMPTS + 1):
                raw_text = chat(
                    target,
                    turn,
                    temperature=float(payload.get("temperature", 0.4)),
                    timeout=LLM_TIMEOUT_SECONDS,
                    extra={key: value for key, value in payload.items() if key != "temperature"},
                    max_retries=configured_max_retries(db),
                    call=call,
                    label="调用 LLM" if attempt == 0 else "重新生成 JSON",
                    allow_response_format_fallback=allow_response_format_fallback,
                    on_downgrade=_note_downgrade,
                )
                text = raw_text.strip()
                if not wants_json:
                    bad = None
                    break
                try:
                    parsed = _json_result(text, raw_text, config, target.model, used_tier=used_tier)
                except _BadJson as exc:
                    bad = exc
                    if attempt >= JSON_REPAIR_ATTEMPTS:
                        break
                    # 把它自己的回答和错处一起发回去 —— 只说"错了"它不知道改哪儿。
                    turn = [*turn, {"role": "assistant", "content": text}, {"role": "user", "content": exc.feedback}]
                    continue
                bad = None
                break
            # 降级有成本(每一次都是一个多出来的往返)。账上该看得见 —— 否则"这条流程为什么
            # 比预期贵"永远查不出来。
            if downgrades:
                call.annotate(response_format_downgrades=downgrades)
    except AiChatError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if bad is not None:
        raise WorkflowDomainError(bad.key, params=bad.params, details=bad.details)
    result: dict[str, Any] = {"text": text}
    if wants_json:
        result["json"] = parsed
    # **接出去**:后面的节点和用户都该看得见这一轮实际跑在哪一档。声明在 NODE_TYPES 里,
    # 由 test_executor_outputs_are_declared 强制两边对齐。
    result["response_format_used"] = used_tier
    return result


@register("translate_lines")
def translate_lines(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """整轨一次翻完。

    **收什么都行:一列字符串、一列带 `text` 的段落、一段 JSON 数组或一行一条的文本**
    (见 common.text_lines)。上游最常见的是逐字稿的 segments(每段带 start/end/text),而把整个
    段落对象交给翻译引擎就是把一坨 JSON 送去翻译 —— 此前的逐句循环靠模板里写
    `{{loop.item.text}}` 绕开这件事,那是把节点的职责推给了调用方。

    逐句循环也能得到同样的结果,但那是 N 次**串行**节点调用、每次一个新连接;免费端点按 IP
    限流,串起来正好踩在它的节流上(真机上第 1/31 次就 429)。这里走 translate_many:
    8 路并发、共用一条会重试的连接。

    **顺序即对齐**:第 i 条译文配第 i 段的时间码,所以空段落也要占住自己的位置 ——
    translate_many 对空串返回空串,不压缩列表。
    """
    from app.domain.translate import translate_many

    texts = text_lines(config.get("texts"))
    if not texts:
        return {"texts": [], "count": 0}
    with workspace_scope(getattr(workflow, "workspace_id", "") or ""):
        translated = translate_many(
            db,
            texts,
            str(config.get("target_lang") or "en"),
            user_id=current_actor(db),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
            model=str(config.get("model") or ""),
            surface="automation",
        )
    return {"texts": translated, "count": len(translated)}


@register("translate")
def translate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.translate import translate as translate_text

    text = str(config.get("text", ""))
    if not text.strip():
        return {"text": ""}
    # 工作流跑在后台线程,没有 HTTP 请求把工作区绑进上下文 —— 显式圈一下,AI 翻译的用量才有归属。
    # workflow 可能为 None(单元测试直接调节点);那时没有归属可绑,记账会跳过并 warning。
    with workspace_scope(getattr(workflow, "workspace_id", "") or ""):
        translated = translate_text(
            db,
            text,
            str(config.get("target_lang") or "en"),
            user_id=current_actor(db),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
            model=str(config.get("model") or ""),
            surface="automation",
        )
    return {"text": translated}
