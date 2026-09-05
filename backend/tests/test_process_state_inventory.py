"""结构性约束:**每一处模块级可变状态都在 docs/PROCESS_STATE.md 里有交代**。

后端是单进程 uvicorn,而不少地方就建立在这个前提上 —— 令牌刷新的租约、发布任务的认领、
OAuth 的待完成流。这些说明此前各自躺在自己文件的注释里:单看任何一处都不显眼,于是
「能不能起第二个后端进程」这个问题没有任何一个地方回答得了,而它恰恰是把后端搬上服务器
时第一个要回答的。

清单写下来还不够,它会腐烂 —— MCP.md 就腐烂过(54 个工具只列了 15 个,缺的全是后加的)。
所以这里做成棘轮:新加的模块级可变状态**必须写进那份清单**并归类,否则这条测试失败。
腐烂的代价在这里格外具体:一份漏了两条的清单会让人以为可以起两个进程。

判据是「运行时真的会变」,不是「长得像容器」:模块级的常量查表满地都是(光
generation/catalog.py 就几十个),把它们算进来的话这份清单会淹掉,而淹掉的清单没人看。
所以只认两种 —— 被 `global` 重新绑定过的,和被下标赋值 / `append`、`pop`、`clear` 这类
方法改过的。
"""

from __future__ import annotations

import ast
import pathlib
import re

RATCHET = True

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
DOC = ROOT / "docs" / "PROCESS_STATE.md"

#: 会就地改容器的方法。漏掉一个的后果是漏报,不是误报。
MUTATORS = frozenset(
    {"append", "add", "pop", "clear", "update", "discard", "setdefault", "remove", "extend", "popitem"}
)


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _mutated_names(tree: ast.Module) -> set[str]:
    """在这个模块里被真正改过的名字(不管它是不是模块级 —— 交集在调用方取)。"""
    touched: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            touched |= set(node.names)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    touched.add(target.value.id)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.attr in MUTATORS
        ):
            touched.add(node.func.value.id)
    return touched


def _live_state() -> set[str]:
    """代码里现有的进程内状态,写成 `app/x.py:_name`。"""
    found: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT / "backend").as_posix()
        for name in _module_level_names(tree) & _mutated_names(tree):
            found.add(f"{relative}:{name}")
    return found


def _documented() -> set[str]:
    """清单里提到的那些。

    认的是行内代码里的 `app/x.py:_name`,表格和列表都能写 —— 归类靠散文表达,
    机器只管"提没提到",别的交给读的人。
    """
    text = DOC.read_text(encoding="utf-8")
    return {f"{path}:{name}" for path, name in re.findall(r"`(app/[\w/]+\.py):(\w+)`", text)}


def test_新加的进程内状态要写进清单() -> None:
    missing = sorted(_live_state() - _documented())
    assert not missing, (
        "这些模块级可变状态没有出现在 docs/PROCESS_STATE.md 里。它们决定了重启会丢什么、"
        "以及能不能起第二个后端进程 —— 归到那份清单的某一节里(哪怕是第四节「纯缓存」):\n  "
        + "\n  ".join(missing)
    )


def test_清单里不留已经不存在的条目() -> None:
    """棘轮只能缩:删掉一处状态时清单要跟着删,否则它会慢慢变成一份历史记录。"""
    stale = sorted(_documented() - _live_state())
    assert not stale, (
        "docs/PROCESS_STATE.md 提到的这些已经不在代码里了,删掉对应条目:\n  " + "\n  ".join(stale)
    )
