"""读目录里那几格文案的地方,**要么翻,要么明说自己在传 key**。

## 为什么这条看不出来

工作流节点目录从"存中文"改成"存 key"时,出口那一处翻了,并且上了棘轮
(`test_工作流节点目录里存的是_key_不是文案`)—— 但那条守的是「**目录里**不许出现中文」,
守不到「**读目录的人**有没有翻」。两处因此漏掉:

- `graph_ops.add_node` 在没给名字时回退到 `NODE_TYPES[type]["label"]` —— 智能体建的节点
  在画布上从此叫 `wfNode_scene_render`,而且**随图落库**:这是写进用户数据的错,不只是显示错,
  改对翻译之后还得靠迁移救回来;
- `engine.node_label()` 同样回退,而这个值进 `workflow.node.*` 事件的 payload、落进
  `task_events`,前端的执行历史原样画出来 —— 而前端**没有任何 `wfNode_` 的字典**
  (全仓 `frontend/src` 搜 `wfNode_`,零命中)。

两处的回退分支平时都走不到(模板和手工建的节点都有名字),只有智能体建的、或者名字被清空的
才会露出来 —— 而那正是最难发现的那一类。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
#: 这几格存的是 i18n key,不是人话。
KEY_FIELDS = {"label", "description", "category"}

#: 读了但**故意不翻**的地方 —— 它在往下传 key,由更外面那一层翻。每一条都要写清楚为什么。
PASSES_THE_KEY: dict[str, str] = {
    "domain/workflows/engine.py:node_label_key": "把 key 一起放进事件 payload,出口按读的人的语言重翻",
    "domain/agent/confirmable/graphs.py:external_warning": "留成 fragment 交给 ConfirmationOut 渲染(那里才是出口)",
}


def _reads() -> list[tuple[str, int, bool]]:
    """`NODE_TYPES[...]["label"]` 这类读取:(位置, 行号, 同一处有没有 t()/fragment())。"""
    found: list[tuple[str, int, bool]] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "migrations.py":
            continue  # 迁移里提到它是在说明历史,不是在读它
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Subscript):
                    continue
                if not (isinstance(node.slice, ast.Constant) and node.slice.value in KEY_FIELDS):
                    continue
                source = ast.unparse(node)
                if "NODE_TYPES" not in source:
                    continue
                # 同一个函数里出现 t( / fragment( 就算翻了(不强求同一行:拆成两步是常见写法)
                body = ast.unparse(func)
                translated = "t(" in body or "fragment(" in body
                rel = path.relative_to(APP).as_posix()
                found.append((f"{rel}:{func.name}", node.lineno, translated))
    return found


def test_读了目录文案就要翻() -> None:
    reads = _reads()
    assert reads, "一处都没找到 —— 这条测试大概看错了地方"
    offenders = [
        f"{where}(第 {line} 行)"
        for where, line, translated in reads
        if not translated and where not in PASSES_THE_KEY
    ]
    assert not offenders, (
        "这几处把目录里的 i18n key 当人话用了 —— 界面上会直接露出 `wfNode_xxx`:\n  "
        + "\n  ".join(offenders)
    )


def test_传key的豁免要写明理由() -> None:
    assert len(PASSES_THE_KEY) <= 2
    for where, reason in PASSES_THE_KEY.items():
        assert len(reason.strip()) > 10, f"{where} 的理由太短"


def test_不把key写进用户数据() -> None:
    """`graph_ops` 那一处尤其严重:它**随图落库**,改对翻译之后还得靠迁移救。"""
    from app.domain.workflows import graph_ops
    from tests.util import executable_source

    # **剥掉注释再看**:解释这次改动的注释里正好引用了那段旧代码,直接搜源码文本会打到自己
    # 身上(这一轮同一个错犯了五次,见 tests/util.executable_source)。
    assert 'NODE_TYPES[node_type]["label"]' not in executable_source(graph_ops), (
        "又把 key 当默认名字写进图里了"
    )


def test_前端根本没有这份字典() -> None:
    """钉住前提:后端不翻的话,没有任何别的地方会翻。"""
    frontend = APP.parent.parent / "frontend" / "src"
    hits = [p.name for p in frontend.rglob("*.ts") if "wfNode_" in p.read_text(encoding="utf-8")]
    hits += [p.name for p in frontend.rglob("*.tsx") if "wfNode_" in p.read_text(encoding="utf-8")]
    assert not hits, f"前端出现了 wfNode_ 字典({hits})—— 那这条规矩要重新讨论"
