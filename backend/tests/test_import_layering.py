from __future__ import annotations

import ast
import collections
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
    mods = []
    # 看**当前工作树**而不是 git 索引。新增模块尚未 git add 时正是最该检查分层的时刻；
    # 旧实现看不见它，会把 `app.ai.media_transfer` 错认成已知父包
    # `app.ai.providers`，既可能制造假环，也可能漏掉新文件里的真环。
    for path in sorted((BACKEND / APP).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(BACKEND).as_posix()
        name = rel[:-3].replace("/", ".")
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods.append((name, path))
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

    packages = {name for name, path in mods if path.name == "__init__.py"}

    def targets_of(node: ast.Import | ast.ImportFrom, importer: str) -> list[str]:
        """一条 import 语句真正拉进来的模块。

        `from app.domain import agent` 拉进来的是 **app.domain.agent** 这个子模块,不是 app.domain 包本身。
        此前只看 `node.module`,于是这种写法全都记成了对包的依赖 —— 包级的环、跨层的边在这里整类隐身。
        相对导入(`from . import x`、`from .sub import y`)此前也整个被跳过。
        """
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        base = node.module or ""
        if node.level:
            anchor = importer if importer in packages else importer.rpartition(".")[0]
            for _ in range(node.level - 1):
                anchor = anchor.rpartition(".")[0]
            base = f"{anchor}.{base}" if base else anchor
        found = []
        for alias in node.names:
            submodule = f"{base}.{alias.name}"
            found.append(submodule if submodule in known else base)
        return found

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
            for dotted in targets_of(node, name):
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


def test_领域连延迟导入也不认识集成层() -> None:
    """**这一条连函数内的延迟导入也不放过。**

    上一条允许延迟导入,是因为「运行时才需要上层」有正当的场合(迁移)。领域层对集成层没有:领域要的外部
    能力经 ai/providers 的公共入口拿,集成层(飞书这类)是**调用领域的一方**。此前唯一的一处是引擎目录
    延迟 import integrations.volc_openapi 去拉火山账号的音色 —— 那是「怎么跟火山说话」,已经搬进
    ai/providers/adapters/bytedance/volcano/speakers。
    """
    graph = _graph(include_lazy=True)
    violations = sorted(
        f"{src} → {dst}"
        for src, dsts in graph.items()
        if src.startswith("app.domain")
        for dst in dsts
        if dst == "app.integrations" or dst.startswith("app.integrations.")
    )
    assert not violations, "领域层 import 了集成层(含函数内的延迟导入):\n  " + "\n  ".join(violations)


def test_top_level_imports_are_acyclic() -> None:
    """只看顶层导入(不含函数内延迟导入),依赖图必须无环。

    这是最基本的一条:顶层成环意味着 import 顺序决定成败。
    """
    assert not _cycles(_graph(include_lazy=False))


#: 算上函数内延迟导入之后**还在环里的模块**。只减不增的棘轮。
#:
#: 这份清单曾经是空的 —— 但那是个假象:`from app.domain.workflows import executors` 这类写法被记成了对**包**的
#: 依赖,相对导入干脆整个没看,于是包和子模块之间的环、跨子模块的环整类隐身。解析修好之后当场露出十一处;
#: 顶层导入里的那些已经拆掉(注册表挪进 registry.py,见 workflows/executors 与 sequences/undo),剩下的都是
#: 函数内的延迟导入,冻结在这里。
#:
#: 规则:新模块进环 → 红;有模块出了环 → 也红,把它从这里删掉(不留一扇随时可以走回来的门)。
LAZY_CYCLE_MODULES = frozenset(
    {
        # TTS 引擎目录与语言表互相查。
        "app.ai.runtime.config", "app.ai.runtime.f5_models", "app.ai.runtime.tts_language", "app.ai.runtime.tts_models",
        # 插件实例、状态、工具调用、宿主能力通知:实例变了要通知能力表,工具调用又要读实例。
        "app.domain.plugins.host_capabilities", "app.domain.plugins.instances", "app.domain.plugins.state",
        "app.domain.plugins.tools",
        "app.domain.plugins.bundled", "app.domain.plugins.packages",
        # 生成解析要查供应商模型,供应商模型又要问生成目录「这个模型是哪一类」。
        "app.domain.generation", "app.domain.generation.operations", "app.domain.generation.resolution",
        "app.domain.providers.models",
        # 工作流引擎 ⇄ 执行器:子工作流节点回头调引擎,引擎按注册表找执行器。
        "app.domain.workflows.engine", "app.domain.workflows.executors", "app.domain.workflows.executors.ai",
        "app.domain.workflows.executors.basic", "app.domain.workflows.executors.common",
        "app.domain.workflows.executors.content", "app.domain.workflows.executors.dub_lipsync",
        "app.domain.workflows.executors.entities", "app.domain.workflows.executors.loops",
        "app.domain.workflows.executors.scenes", "app.domain.workflows.executors.subjobs",
        "app.domain.workflows.executors.subworkflow", "app.domain.workflows.executors.talking",
        "app.domain.workflows.field_options", "app.domain.workflows.templates",
    }
)


def test_no_cycle_survives_even_lazy_imports() -> None:
    """把函数内延迟导入也算上,环里的模块**只减不增**(见 LAZY_CYCLE_MODULES)。

    这里曾经允许过一个:core.db ⇄ db.models —— Base 定义在 core.db,models 依赖它,而 init_db
    又要回头 import models 才能 create_all,当时判成"SQLAlchemy 的标准形态,无法消除"。
    **那个判断是错的**:环的根源不是 Base,是 `core/db.py` 同时当了底座和迁移编排器。迁移搬去
    `app/db/migrations.py` 之后,init_db 不再需要从底座回头引 models,环自己就没了。
    """
    in_cycles = {module for cycle in _cycles(_graph(include_lazy=True)) for module in cycle}
    joined = sorted(in_cycles - LAZY_CYCLE_MODULES)
    assert not joined, (
        "这些模块新进了循环依赖(通常是某处用函数内 import 绕开了分层):\n  " + "\n  ".join(joined)
    )
    left = sorted(LAZY_CYCLE_MODULES - in_cycles)
    assert not left, "这些模块已经不在环里了,把它们从 LAZY_CYCLE_MODULES 里删掉:\n  " + "\n  ".join(left)


def _package_of(module: str) -> str:
    """包级粒度:app.domain.<包>、app.ai.<包>…… 两层以下的模块归到它所在的那个包。"""
    parts = module.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else module


def _package_graph(include_lazy: bool) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for src, dsts in _graph(include_lazy=include_lazy).items():
        for dst in dsts:
            if _package_of(src) != _package_of(dst):
                graph[_package_of(src)].add(_package_of(dst))
    return graph


def test_packages_do_not_import_each_other_in_a_circle() -> None:
    """包级:顶层导入里,领域包之间不许成环。

    模块级无环挡不住这一种:providers.connections 为了一个 vendor 前缀在顶层 import 了生成域,而生成域
    本来就依赖供应商 —— 两个包就此互相认识,只是没有哪两个**模块**恰好首尾相接。同样的还有笔记为了
    一个共享种类名 import 了智能体(智能体经工作流又依赖笔记)。两处都已拆开:vendor 命名约定挪进
    providers/plugin_vendor,共享种类名挪进 sharing。
    """
    cycles = _cycles(_package_graph(include_lazy=False))
    assert not cycles, "这些包在顶层互相 import:\n  " + "\n  ".join(" ⇄ ".join(c) for c in cycles)


#: 算上延迟导入之后仍在包级环里的领域包。只减不增的棘轮,规则同 LAZY_CYCLE_MODULES。
#:
#: 它们大多是**往下**的正常依赖(工作流用账单、用供应商),被少数几条往回走的延迟导入串成了一个环:
#: 供应商模型回头问生成目录、素材导入回头建资产与文档、资产回头调工作流画图。拆掉那几条回边,
#: 这个环就散了 —— 在那之前,至少不许有新的包被卷进来。
LAZY_CYCLE_PACKAGES = frozenset(
    {
        "app.domain.ai_chat", "app.domain.analysis", "app.domain.assets", "app.domain.billing",
        "app.domain.documents", "app.domain.entities", "app.domain.generation", "app.domain.providers",
        "app.domain.publish", "app.domain.render", "app.domain.scenes", "app.domain.translate",
        "app.domain.voices", "app.domain.workflows",
    }
)


def test_the_package_level_cycle_only_shrinks() -> None:
    in_cycles = {package for cycle in _cycles(_package_graph(include_lazy=True)) for package in cycle}
    joined = sorted(in_cycles - LAZY_CYCLE_PACKAGES)
    assert not joined, "这些包新被卷进了包级循环依赖:\n  " + "\n  ".join(joined)
    left = sorted(LAZY_CYCLE_PACKAGES - in_cycles)
    assert not left, "这些包已经不在环里了,把它们从 LAZY_CYCLE_PACKAGES 里删掉:\n  " + "\n  ".join(left)
