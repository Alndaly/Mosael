from __future__ import annotations

import ast
import collections
import subprocess
from pathlib import Path

"""模块依赖的结构性约束。

这两条约束是这套代码库现在真实成立的性质(实测:零反向依赖、顶层导入图无环),不是愿望。
写成测试是因为它们**很容易在不知不觉中被破坏** —— 领域层想给飞书推个消息、随手 import 一下,
环就成了;而循环依赖不会立刻报错,它只是逼着后来人到处写函数内延迟导入,直到某天导入顺序
一变就炸。曾经就出现过 domain.agent.confirmations ⇄ integrations.feishu.service 这一个环
(领域层回调集成层),靠把推送挪到路由层解掉。
"""

BACKEND = Path(__file__).resolve().parents[1]
APP = "app"

#: 底层不许认识上层。api 是组合层,可以认识所有人;反过来不行。
LOWER_LAYERS = ("app.domain", "app.core", "app.media", "app.ai", "app.audio", "app.integrations")


def _modules() -> list[tuple[str, Path]]:
    out = subprocess.run(["git", "ls-files", "app"], cwd=BACKEND, capture_output=True, text=True).stdout
    mods = []
    for rel in out.split():
        if not rel.endswith(".py"):
            continue
        # git ls-files 会列出"已删除但还没暂存"的文件。删一个模块之后到 git add 之前,
        # 这里会去打开一个不存在的路径,让整组分层测试红在一个与分层无关的原因上。
        if not (BACKEND / rel).exists():
            continue
        name = rel[:-3].replace("/", ".")
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods.append((name, BACKEND / rel))
    return mods


def _graph(include_lazy: bool = True) -> dict[str, set[str]]:
    mods = _modules()
    known = {name for name, _ in mods}

    def resolve(dotted: str) -> str | None:
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in known:
                return candidate
        return None

    graph: dict[str, set[str]] = collections.defaultdict(set)
    for name, path in mods:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        inner = set()
        if not include_lazy:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner.update(id(sub) for sub in ast.walk(node))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if not include_lazy and id(node) in inner:
                continue
            targets = (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [a.name for a in node.names]
            )
            for dotted in targets:
                hit = resolve(dotted or "")
                if hit and hit != name:
                    graph[name].add(hit)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan 强连通分量;长度 >1 的即循环依赖。"""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for node in list(graph):
        if node not in index:
            visit(node)
    return found


def test_lower_layers_never_import_the_api_layer() -> None:
    """领域/核心/媒体/集成 不许反向依赖 app.api。

    api 是薄转译层:它可以认识所有人,所有人不该认识它。破了这条,领域逻辑就没法脱离 HTTP
    单独测,也没法被 worker / MCP / 飞书这些非 HTTP 入口复用。
    """
    graph = _graph(include_lazy=True)
    violations = [
        f"{src} → {dst}"
        for src, dsts in graph.items()
        if src.startswith(LOWER_LAYERS)
        for dst in dsts
        if dst.startswith("app.api")
    ]
    assert not violations, "底层模块反向依赖了 api 层:\n  " + "\n  ".join(sorted(violations))


def test_top_level_imports_are_acyclic() -> None:
    """只看顶层导入(不含函数内延迟导入),依赖图必须无环。

    这是最基本的一条:顶层成环意味着 import 顺序决定成败。
    """
    assert not _cycles(_graph(include_lazy=False))


def test_only_the_sqlalchemy_base_cycle_survives_lazy_imports() -> None:
    """把函数内延迟导入也算上,只允许 core.db ⇄ db.models 这一个环。

    那个环是 SQLAlchemy 的标准形态:Base 定义在 core.db,models 依赖它,而 init_db 又要回头
    import models 才能 create_all —— 无法消除,也无害。

    除它之外的任何环都说明有人用延迟导入绕过了分层。允许它「暂时能跑」正是循环依赖的危险之处,
    所以这里用白名单而不是计数。
    """
    allowed = {("app.core.db", "app.db.models")}
    actual = {tuple(c) for c in _cycles(_graph(include_lazy=True))}
    unexpected = actual - allowed
    assert not unexpected, (
        "出现了新的循环依赖(通常是某处用函数内 import 绕开了分层):\n  "
        + "\n  ".join(" ⇄ ".join(c) for c in sorted(unexpected))
    )
