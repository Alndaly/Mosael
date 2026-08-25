from __future__ import annotations

import ast
from pathlib import Path

from app.domain.workflows import NODE_TYPES
from app.domain.generation.operations import parse_source_assets

"""节点声明的配置项,必须覆盖执行器真正读取的那些。

这条约束来自一个**沉默**的缺口:`ai_generate` 的执行器一直在读 `negative_prompt` /
`parameters` / `source_assets`,但节点类型里没声明它们 —— 于是编辑器渲染不出输入框、
AI 助手也不知道它们存在。表现不是报错,而是「工作流里做不出竖屏视频」,而代码看上去哪儿都对。

声明即接口:执行器读什么,节点就得声明什么,否则那份能力对用户不存在。
"""

EXECUTORS_DIR = Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "executors"

#: 执行器读得到、但**刻意**不作为用户可填项的键。加进来必须写明理由。
NOT_USER_CONFIGURABLE: dict[str, set[str]] = {
    # 循环体/子图是内嵌子图,由画布编辑,不是表单字段。
    "loop_foreach": {"body"},
    "loop_while": {"body"},
    "subgraph": {"body"},
}


def _executor_config_keys() -> dict[str, set[str]]:
    """扫执行器源码里的 `config.get("x")`,按 @register("节点类型") 归组。"""
    found: dict[str, set[str]] = {}
    for path in sorted(EXECUTORS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            registered = [
                deco.args[0].value
                for deco in node.decorator_list
                if isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Name)
                and deco.func.id == "register"
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
                and isinstance(deco.args[0].value, str)
            ]
            if not registered:
                continue
            keys: set[str] = set()
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "config"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                ):
                    keys.add(sub.args[0].value)
            for node_type in registered:
                found.setdefault(node_type, set()).update(keys)
    return found


def test_executors_only_read_declared_config() -> None:
    missing: list[str] = []
    for node_type, keys in _executor_config_keys().items():
        declared = set(NODE_TYPES.get(node_type, {}).get("config", {}))
        allowed = NOT_USER_CONFIGURABLE.get(node_type, set())
        for key in sorted(keys - declared - allowed):
            missing.append(f"{node_type}.{key}")
    assert not missing, (
        "执行器读了没声明的配置项 —— 这些能力在编辑器和 AI 助手眼里根本不存在:\n  "
        + "\n  ".join(missing)
    )


def test_the_scan_actually_finds_something() -> None:
    """防止扫描器本身失效(改了装饰器/取值写法后扫不到,上面那条就会永远绿)。"""
    found = _executor_config_keys()
    assert "ai_generate" in found
    assert {"provider", "model", "kind", "prompt", "parameters"} <= found["ai_generate"]


def _ids(value, kind="video") -> list[str]:
    return [item["asset_id"] for item in parse_source_assets(value, kind=kind)]


def test_reference_assets_accept_a_template_string() -> None:
    """参考图/首帧要能接上游节点的输出({{gen-1.asset_id}}),而模板字段只会给到字符串。
    只认列表的话这个字段在编辑器里就没法用。"""
    assert _ids("a\nb") == ["a", "b"]
    assert _ids("a, b") == ["a", "b"]
    assert _ids("a，b") == ["a", "b"], "中文逗号也要认——中文输入法下这是常态"
    assert _ids(["a", " ", "b"]) == ["a", "b"]
    assert _ids("") == []
    assert _ids(None) == []


def test_模板字符串里也能写角色() -> None:
    """`{{gen-1.asset_id}}:last_frame` —— 上游产出的那张图当尾帧。
    不支持的话,工作流里就只能做首帧,而首尾帧恰恰是工作流最想串的形状。"""
    assert parse_source_assets("a:last_frame\nb", kind="video") == [
        {"asset_id": "a", "role": "last_frame"},
        {"asset_id": "b", "role": "first_frame"},
    ]


def test_不写角色时按介质兜底() -> None:
    """图生视频的那张图是首帧,图生图的那张图是参考 —— 这是两种介质里最常见的那个意思。"""
    assert parse_source_assets("a", kind="video")[0]["role"] == "first_frame"
    assert parse_source_assets("a", kind="image")[0]["role"] == "reference_image"


def test_角色写错了当场拦住() -> None:
    """默默当成首帧的话,用户会拿到一段「怎么改提示词都不对」的视频。"""
    import pytest

    from app.domain.generation.operations import GenerationDomainError

    with pytest.raises(GenerationDomainError, match="未知的素材角色"):
        parse_source_assets("a:头一帧", kind="video")
