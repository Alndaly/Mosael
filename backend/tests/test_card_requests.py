"""确认卡**收什么**只有一份:每种卡的 `request` 模型(registry.CardRequest)。工具那侧拼的、卡这侧收的必须是同一套键。

此前载荷是隐式约定 —— 工具在 app/agent_tools 里拼 dict,卡在 confirmable/*.py 里 `payload.get(...)` 反解,改一个参数名不会在任何
地方报错。现在:开卡时按模型校验(多键、缺必填、类型不对都拒);这里再静态比对每一处 `open_card` 拼的键,不用等到有人点开那张卡。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import app.agent_tools  # noqa: F401 — 导入即登记工具
from app.domain.agent.confirmable.registry import CardRequest, tool_spec, tool_specs


def _open_card_payloads() -> list[tuple[str, str, set[str]]]:
    """每一处 `open_card({...})`:(哪个文件, 卡名, 字面写出的载荷键)。键由表达式拼出(**展开、变量)的跳过。"""
    found = []
    for path in sorted(pathlib.Path("app/agent_tools").glob("*.py")):
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "open_card" and call.args):
                continue
            top = call.args[0]
            if not isinstance(top, ast.Dict):
                continue
            fields = {k.value: v for k, v in zip(top.keys, top.values) if isinstance(k, ast.Constant)}
            tool, payload = fields.get("tool"), fields.get("payload")
            if not isinstance(tool, ast.Constant) or not isinstance(payload, ast.Dict):
                continue
            keys = {k.value for k in payload.keys if isinstance(k, ast.Constant)}
            for spread in (v for k, v in zip(payload.keys, payload.values) if k is None):
                if isinstance(spread, ast.IfExp) and isinstance(spread.body, ast.Dict):
                    keys |= {k.value for k in spread.body.keys if isinstance(k, ast.Constant)}
            found.append((path.name, tool.value, keys))
    return found


OPENED = _open_card_payloads()


def test_scan_sees_the_tools() -> None:
    assert len(OPENED) >= 50, "扫描面塌了:open_card 的写法变了?"


@pytest.mark.parametrize(("where", "tool", "keys"), OPENED, ids=[f"{w}:{t}" for w, t, _ in OPENED])
def test_the_tool_sends_only_what_the_card_accepts(where: str, tool: str, keys: set[str]) -> None:
    spec = tool_spec(tool)
    assert spec is not None, f"{where} 给 {tool} 开卡,但没有这种卡"
    accepted = {field.alias or name for name, field in spec.request.model_fields.items()}
    assert keys <= accepted, f"{where} 给 {tool} 拼了卡不收的键:{sorted(keys - accepted)}"
    required = {field.alias or name for name, field in spec.request.model_fields.items() if field.is_required()}
    assert required <= keys, f"{where} 给 {tool} 少拼了必填的键:{sorted(required - keys)}"


def test_every_card_declares_what_it_accepts_and_refuses_strays() -> None:
    for name, spec in tool_specs().items():
        assert issubclass(spec.request, CardRequest), name
        assert spec.request.model_config.get("extra") == "forbid", f"{name} 的请求模型不拒多余的键"
