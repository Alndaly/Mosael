"""插件节点在**每一条**校验路径上都认得出来,而不只是保存和运行那两条。

## 为什么这条看不出来

`plugin_node_types` 存在的全部意义,是让插件节点"和内置节点没有区别" —— 前端因此不需要知道
"这一项是插件来的"。而 `validate_graph` 的 `extra_types` 是**可选参数**,少传一个不会有任何
提示,只会让那个节点被判成未知类型,报出:

    节点 X 来自插件「…」的工具 …,该插件未安装或未启用

**这是一句指向别处的错误。** 插件明明装着、开着,画布上跑得好好的,而用户会照着这句话去插件
页找问题。真实发生过两处:

- AI 编排(`ai_edit`):提示词要求模型"保留用户没让你改的部分",于是图里原样留着的插件节点
  必然被判未知 —— **含插件节点的工作流一律编排失败**,两次重试都一样;
- 智能体开的确认卡(`confirmable/automation`):智能体完全可以用插件节点搭图。

保存和运行那两条路一直是对的,所以问题只出现在"另外那几条"。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

#: 拿不到 db、因而查不出插件节点的调用点。**每一条都要写清楚为什么**,这张表只减不增。
NO_DB: dict[str, str] = {
    # 循环体 / 子图是**图里的一段**,它的类型已经由外层那次校验管过了 —— 外层带着 extra_types。
    "domain/workflows/__init__.py:validate_body_graph": "纯图校验,拿不到 db;外层那次校验已经带了 extra_types",
}


def _calls() -> list[tuple[str, int, bool]]:
    found: list[tuple[str, int, bool]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                name = getattr(inner.func, "id", None) or getattr(inner.func, "attr", None)
                if name != "validate_graph":
                    continue
                rel = path.relative_to(APP).as_posix()
                said = any(kw.arg == "extra_types" for kw in inner.keywords)
                found.append((f"{rel}:{node.name}", inner.lineno, said))
    return found


def test_每一处校验都认得插件节点() -> None:
    calls = _calls()
    assert len(calls) >= 4, f"只找到 {len(calls)} 处 validate_graph(),这条测试大概看错了地方"
    missing = [
        f"{where}(第 {line} 行)"
        for where, line, said in calls
        if not said and where not in NO_DB
    ]
    assert not missing, (
        "这几处校验不认得插件节点 —— 用户的图里有插件节点时会被判成未知类型,而报出来的话"
        "指向的是插件页:\n  " + "\n  ".join(missing)
    )


def test_豁免清单只减不增() -> None:
    assert len(NO_DB) <= 1
    for where, reason in NO_DB.items():
        assert len(reason.strip()) > 10, f"{where} 的理由太短"


def test_可用节点类型只有一处组装() -> None:
    """接口层和 AI 编排此前各组一份,而 AI 编排那份**只有内置节点**。"""
    import inspect

    from app.domain.workflows import available_node_types

    source = inspect.getsource(available_node_types)
    assert "plugin_node_types" in source

    for module in ("app/api/routes/workflows.py", "app/domain/workflows/ai_edit.py"):
        text = (APP.parent / module).read_text(encoding="utf-8")
        assert "available_node_types(" in text, f"{module} 又自己组了一份"


def test_给模型的是人话不是i18n_key() -> None:
    """`NODE_TYPES` 里 label/description 存的是 key(由 test_backend_i18n 那道棘轮强制),
    出口才翻。AI 编排原先原样发了出去 —— 模型收到的每个节点说明是一串 `wfNode_xxx_desc`,
    而表现只是"编排质量下降",没人会把它归因到提示词里少了翻译。"""
    text = (APP / "domain" / "workflows" / "ai_edit.py").read_text(encoding="utf-8")
    assert 't(meta["label"], locale)' in text, "给模型的 label 又变回 key 了"
