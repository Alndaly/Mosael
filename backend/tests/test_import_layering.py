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
LOWER_LAYERS = ("app.domain", "app.core", "app.media", "app.ai", "app.ai.runtime", "app.integrations")


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


#: 分层的**顺序**,从下到上。下标越小越底层,底层不许认识上层。
#:
#: 这比"不许依赖 api"那条严:那条只钉住了最上面一层,而真正会悄悄长出来的是中间的反向边 ——
#: `db/migrations.py` 曾在顶层 import `ai.runtime` 与 `domain.voices`(迁移动作住在被迁移的
#: 那一侧),于是**加载一个迁移模块会连带拉起半个应用**。它没被上面那条拦住,因为 db 当时
#: 根本不在名单里。
LAYER_ORDER = ("app.core", "app.db", "app.media", "app.ai", "app.domain", "app.integrations", "app.api")


def _layer_of(module: str) -> int:
    """这个模块属于第几层。不在分层里的(app.main、app.workers)回 -1,不参与判定。"""
    for index, prefix in enumerate(LAYER_ORDER):
        if module == prefix or module.startswith(prefix + "."):
            return index
    return -1


def test_下层不认识上层() -> None:
    """**只看顶层 import。**

    函数内的延迟导入在这里是允许的 —— 那是"运行时才需要"的正当表达(迁移只在 init_db 那一刻
    跑一次,它对上层的需要确实是运行时的)。而顶层 import 是**加载时的绑定**:它把两层焊死,
    代价是 import 一个底层模块就要把上层整棵拉起来,而那恰恰是让循环依赖有机可乘的形状。
    """
    graph = _graph(include_lazy=False)
    violations = []
    for src, dsts in graph.items():
        src_layer = _layer_of(src)
        if src_layer < 0:
            continue
        for dst in dsts:
            dst_layer = _layer_of(dst)
            if dst_layer > src_layer:
                violations.append(f"{src} → {dst}    ({LAYER_ORDER[src_layer]} 认识了 {LAYER_ORDER[dst_layer]})")

    assert not violations, (
        "下层在**顶层** import 了上层。真的需要的话请挪进函数体 —— 那表示「运行时才需要」,"
        "而不是「加载时就绑死」:\n  " + "\n  ".join(sorted(violations))
    )


def test_top_level_imports_are_acyclic() -> None:
    """只看顶层导入(不含函数内延迟导入),依赖图必须无环。

    这是最基本的一条:顶层成环意味着 import 顺序决定成败。
    """
    assert not _cycles(_graph(include_lazy=False))


def test_no_cycle_survives_even_lazy_imports() -> None:
    """把函数内延迟导入也算上,**一个环都不许有**。

    这里曾经允许过一个:core.db ⇄ db.models —— Base 定义在 core.db,models 依赖它,而 init_db
    又要回头 import models 才能 create_all,当时判成"SQLAlchemy 的标准形态,无法消除"。

    **那个判断是错的**:环的根源不是 Base,是 `core/db.py` 同时当了底座和迁移编排器。迁移搬去
    `app/db/migrations.py` 之后,init_db 不再需要从底座回头引 models,环自己就没了。

    所以白名单清空。留着一个已经不存在的豁免,等于给它留一扇随时可以走回来的门。
    """
    allowed: set[tuple[str, ...]] = set()
    actual = {tuple(c) for c in _cycles(_graph(include_lazy=True))}
    unexpected = actual - allowed
    assert not unexpected, (
        "出现了新的循环依赖(通常是某处用函数内 import 绕开了分层):\n  "
        + "\n  ".join(" ⇄ ".join(c) for c in sorted(unexpected))
    )
