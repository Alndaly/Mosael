"""这个端点能不能把 JSON Schema 当成硬约束。

三档 `response_format` 的差别在**什么时候起作用**:`json_schema` + strict 是在生成的那一刻
约束解码器(模型吐不出不合规的 token);`json_object` 只保证语法合法;`text` 什么都不保证。

而**各家支持的档位不一样**,不支持时的表现是**静默的** —— 参数要么被忽略,要么被网关降级,
两种都不会告诉任何人。于是用户在节点上写着 strict,实际跑的是纯文本。两次真实失败都由此而来。
"""

from __future__ import annotations

from app.domain.structured_output import effective_support, known_support
from app.domain.workflows.executors.ai import _honour_structured_output


def test_查证过的结论() -> None:
    assert known_support("openai") is True
    #: DeepSeek 官方文档只有 json_object,没有 json_schema(2026-09 查证)。
    assert known_support("deepseek") is False


def test_没查证过的返回未知而不是不支持() -> None:
    """中转的 vendor 一律是 openai-compatible,后面挂的可能是任何一家。

    猜"支持"会让不支持的端点白撞一次 400;猜"不支持"会让支持的端点白白失去硬约束。
    两边都有代价,所以不猜。
    """
    assert known_support("openai-compatible") is None
    assert known_support("") is None


def test_用户填的优先于查证结论() -> None:
    """查证的是"这个供应商",而用户可能接的是一个我们不认识的兼容实现。"""
    assert effective_support("deepseek", True) is True
    assert effective_support("openai", False) is False
    #: None 是「没设过」,不是「设成了关」—— 这时才轮到查证结论。
    assert effective_support("deepseek", None) is False


def _payload() -> dict:
    return {"response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}}


def test_已知不支持时直接降一档_不白发一次() -> None:
    """已知不支持时那个往返是**必然**白花的:端点会 400,然后我们降一档重来。

    降到 json_object 而不是纯文本:前者至少保证语法合法,而 Schema 正文已经在消息里了
    (见 _schema_for_prompt),形状仍然管得住。
    """
    assert _honour_structured_output(_payload(), False)["response_format"] == {"type": "json_object"}


def test_已知支持或不知道时照发() -> None:
    #: 不知道时照发是对的:网关那条降级链本来就能兜住,只是白花一个往返。
    for supported in (True, None):
        assert _honour_structured_output(_payload(), supported)["response_format"]["type"] == "json_schema"


def test_本来就不是_json_schema_的不动它() -> None:
    plain = {"response_format": {"type": "json_object"}}
    assert _honour_structured_output(dict(plain), False) == plain
    assert _honour_structured_output({}, False) == {}
