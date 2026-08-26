"""JSON 模式下,提示词里必须出现 "json"。

这是 OpenAI 兼容接口的**硬性要求**,不是模型的偏好:不满足时拿到的是

    400 Prompt must contain the word 'json' in some form to use 'response_format' of type 'json_object'

而不是一个凑合的回答。deepseek、月之暗面等跟着 OpenAI 的实现都照做。

此前四个调用点各自拼提示词,谁都没管它。最容易撞上的是**工作流的 LLM 节点** —— 它把
response_format 开放给了用户,而用户的提示词里当然不会无缘无故提到 json,于是选了 JSON
模式就 400。修在共同的出口(domain/ai_chat),四个调用点一起受益。
"""

from __future__ import annotations

import pytest

from app.domain.ai_chat import _satisfy_json_mode

JSON_OBJECT = {"type": "json_object"}
JSON_SCHEMA = {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}


class Test缺了就补:
    def test_json_object_模式补一句(self) -> None:
        messages = [{"role": "user", "content": "给我三个标题"}]
        out = _satisfy_json_mode(messages, JSON_OBJECT)
        assert len(out) == 2
        assert "json" in out[0]["content"].lower()

    def test_json_schema_模式同样要补(self) -> None:
        """这条约束对两种 JSON 形式都成立 —— 只管 json_object 的话,用 schema 的人照样 400。"""
        out = _satisfy_json_mode([{"role": "user", "content": "抽取字段"}], JSON_SCHEMA)
        assert "json" in out[0]["content"].lower()

    def test_补在_system_那一侧(self) -> None:
        """改用户写的那段话会改变他的意图。而这一句说的正是 JSON 模式本来就要求的事,
        不增加任何新约束。"""
        messages = [{"role": "user", "content": "给我三个标题"}]
        out = _satisfy_json_mode(messages, JSON_OBJECT)
        assert out[0]["role"] == "system"
        assert out[-1] == messages[0], "用户那条被改了"


class Test已经有就不动:
    @pytest.mark.parametrize(
        "content", ["返回 JSON", "output json", "请以 json 格式回答", "Return a JSON array"]
    )
    def test_不分大小写地认(self, content: str) -> None:
        messages = [{"role": "user", "content": content}]
        assert _satisfy_json_mode(messages, JSON_OBJECT) == messages

    def test_system_里提到也算(self) -> None:
        messages = [
            {"role": "system", "content": "你只输出 json"},
            {"role": "user", "content": "三个标题"},
        ]
        assert _satisfy_json_mode(messages, JSON_OBJECT) == messages


class Test不是_JSON_模式就别动:
    @pytest.mark.parametrize("fmt", [None, {"type": "text"}, "json_object", {}])
    def test_原样返回(self, fmt) -> None:
        """纯文本调用凭空多一句"用 JSON 回答",模型真的会照做 —— 那是把回答毁掉。"""
        messages = [{"role": "user", "content": "写一首诗"}]
        assert _satisfy_json_mode(messages, fmt) == messages


class Test四个调用点都走这条出口:
    def test_出口只有一处(self) -> None:
        """在 payload 拼好之后统一过一遍,而不是让每个调用点自己记得 —— 那正是此前漏掉的原因。"""
        import pathlib

        source = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "ai_chat.py"
        code = source.read_text(encoding="utf-8")
        # extra 里也可能带 response_format(工作流节点就是),所以这一行必须在 extra 合并**之后**
        merge_at = code.index('payload.update({k: v for k, v in extra.items()')
        guard_at = code.index("payload[\"messages\"] = _satisfy_json_mode(")
        assert merge_at < guard_at, "extra 里的 response_format 会绕过这道保证"
