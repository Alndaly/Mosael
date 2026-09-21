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
