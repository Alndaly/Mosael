"""模型交回的 JSON 不合格时怎么办。

三件事,都来自真实失败:

1. **别把碎片当答案。** 实测:模型返回的大对象自身格式错误(把一个数组用引号包成了字符串,
   里面的引号又没转义),而兜底的"扫到第一个能解析的括号"捞到了那个数组,把答案里的一个字段
   当成整个答案交了出去。用户看到的是「这一长串连续性规则 is not of type 'object'」——
   报错指向了完全错误的地方,比直接说"JSON 没闭合"糟得多。
2. **说清楚哪一格错了。** 「1 is less than the minimum of 2」不说字段、不说第几项,
   而 `json_path` 本来就在异常身上。
3. **给它一次改的机会。** 这类错模型一轮就能自纠;而此前一次不合格就让整条流程作废 ——
   实测那次:67 秒、三次已经成功的付费调用,全废在 200 多个字段里的一个上。
"""

from __future__ import annotations

import json

import pytest
from jsonschema import ValidationError

from app.domain.workflows.executors.ai import (
    JSON_REPAIR_ATTEMPTS,
    _BadJson,
    _json_result,
    _parse_json_response,
    _schema_failure,
)

#: 实测那次返回的形状:外层对象没闭合(数组被引号包住),而里面有一个**能独立解析**的数组。
BROKEN = '{"subject_bible":"两个人","continuity_rules":"["水杯全程同一只","睡姿逐档推进"]","tail":1}'


def test_坏掉的大对象不许被捞成碎片() -> None:
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response(BROKEN)


def test_散文里裹着的那个值照样捞得回来() -> None:
    """这个兜底是为**文本模式**存在的:不认 response_format 的端点会被网关退回纯文本,
    那些模型常常在 JSON 外面加一句话或一圈围栏。这条不能因为上面那条一起被掐掉。"""
    assert _parse_json_response('好的,结果如下:\n{"a": 1}\n希望有用') == {"a": 1}
    assert _parse_json_response('```json\n{"a": 2}\n```') == {"a": 2}


def test_围栏里坏掉的一样照实报() -> None:
    """带围栏但内容本身坏了 —— 它仍然是"在返回 JSON,只是返回坏了",不该去捞碎片。"""
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response('```json\n' + BROKEN + '\n```')


def test_报错要说出是哪一格() -> None:
    error = ValidationError("1 is less than the minimum of 2")
    error.absolute_path.extend(["shots", 8, "duration_seconds"])
    reason, feedback = _schema_failure(error)
    assert "shots" in reason and "8" in reason and "duration_seconds" in reason
    assert "1 is less than the minimum of 2" in reason
    #: 发回给模型的那句话要能让它定位到同一处。
    assert "shots" in feedback


SCHEMA = {
    "type": "object",
    "properties": {"n": {"type": "number", "minimum": 2}},
    "required": ["n"],
    "additionalProperties": False,
}
CONFIG = {"response_format": "json_schema", "json_schema": SCHEMA}


def test_不合格时带着_要怎么跟模型说_一起抛() -> None:
    with pytest.raises(_BadJson) as caught:
        _json_result('{"n": 1}', '{"n": 1}', CONFIG, "some-model")
    bad = caught.value
    assert bad.key == "wfErr_jsonSchemaMismatch"
    assert "n" in bad.reason
    #: 只说"错了"的话模型只能瞎改 —— 要把它自己的回答和错处一起发回去。
    assert "Schema" in bad.feedback
    assert bad.details["raw_response"] == '{"n": 1}'


def test_解析失败时告诉模型怎么重来() -> None:
    with pytest.raises(_BadJson) as caught:
        _json_result(BROKEN, BROKEN, CONFIG, "some-model")
    bad = caught.value
    assert bad.key == "wfErr_llmNotJson"
    #: 这次的毛病正是"把数组包进了字符串",所以那句话要点到它。
    assert "包进字符串" in bad.feedback
    assert bad.details["parse_error"]


def test_合格就直接过() -> None:
    assert _json_result('{"n": 5}', '{"n": 5}', CONFIG, "some-model") == {"n": 5}


def test_重试次数是有限的() -> None:
    """每一次都是一次付费调用。要么第二次就对,要么是提示词和 schema 本身打架 ——
    后者再试十次一样,而账单是真的。"""
    assert JSON_REPAIR_ATTEMPTS == 1


def test_Schema_要贴给模型看() -> None:
    """**这是两次失败的共同根因。**

    Schema 此前只进 `payload.response_format`,而那一项能不能生效完全看供应商:DeepSeek 只支持
    `{"type":"json_object"}`,根本没有 json_schema;不认这个参数的端点还会被网关逐级降级到纯文本。
    于是模型收到的是一句「只输出符合 JSON Schema 的对象」—— 而那个 Schema 它从来没见过。
    """
    from app.domain.workflows.executors.ai import _schema_for_prompt

    text = _schema_for_prompt(CONFIG)
    assert '"minimum":2' in text, "Schema 正文必须在里面,不能只说一句「要符合 Schema」"
    #: 这两条是实测栽过的坑:一次是整份 JSON 没闭合(数组被引号包住、内部引号没转义)。
    assert "包进字符串" in text
    assert "转义" in text


def test_只有纯文本那一轮不贴() -> None:
    """判据是**这一轮要不要 JSON**,不是"有没有 Schema"。

    没有 Schema 时形状约束不了,但「必须是一个 JSON 对象」仍然要说 —— 而且那句话本身就带上了
    DeepSeek 要找的那个 "json"(见上一条)。此前这里返回空串,于是那种节点必然 400。
    """
    from app.domain.workflows.executors.ai import _schema_for_prompt

    assert _schema_for_prompt({"response_format": "text"}) == ""
    assert _schema_for_prompt({}) == ""
    assert _schema_for_prompt({"response_format": "json_schema"}) != ""


def test_json_object_也贴() -> None:
    """那一档只保证「是合法 JSON」,字段形状仍然全靠模型自觉 —— 更需要看见 Schema。"""
    from app.domain.workflows.executors.ai import _schema_for_prompt

    assert '"minimum":2' in _schema_for_prompt({**CONFIG, "response_format": "json_object"})


def test_没有_Schema_的_json_object_也要带上_json_这个词() -> None:
    """DeepSeek 在 `response_format: json_object` 下硬性要求提示词里出现 "json",否则直接 400:
    `Prompt must contain the word 'json' in some form`。

    没给 Schema 的节点此前什么都不贴 —— 那条请求必然失败,用户的任务记录里就躺着这一条。
    """
    from app.domain.workflows.executors.ai import _schema_for_prompt

    text = _schema_for_prompt({"response_format": "json_object"})
    assert text, "没有 Schema 也要贴一句,否则这条请求在 DeepSeek 上必然 400"
    assert "json" in text.lower()


def test_契约只贴一次() -> None:
    """网关降级时也会贴一份契约。两边各贴一次的话,同一份 Schema 会在一次请求里出现两遍 ——
    storyboard 那种 4KB 的 Schema,白烧上千 token。靠同一个标记互相认出来。"""
    from app.domain.ai_chat import JSON_CONTRACT_MARKER, _downgrade_response_format_payload
    from app.domain.workflows.executors.ai import _schema_for_prompt

    contract = _schema_for_prompt(CONFIG)
    assert contract.startswith(JSON_CONTRACT_MARKER)
    payload = {
        "messages": [{"role": "user", "content": "做点什么"}, {"role": "user", "content": contract}],
        "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}},
    }
    downgraded = _downgrade_response_format_payload(payload)
    assert downgraded is not None
    #: 降级发生了(response_format 换档),但没有再多插一条契约。
    assert downgraded["response_format"] == {"type": "json_object"}
    assert len(downgraded["messages"]) == len(payload["messages"])
