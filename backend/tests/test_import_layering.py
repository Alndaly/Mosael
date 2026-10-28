"""结构性约束:**模块依赖(分层 + 无环)** —— 底层不认识上层,谁也不许拿函数内的延迟导入把环藏起来。

这几条约束是这套代码库现在真实成立的性质(实测:零反向依赖、顶层导入图无环、连函数体内的 import 一起算
也只剩冻结在棘轮里的那些环),不是愿望。写成测试是因为它们**很容易在不知不觉中被破坏** —— 领域层想给
飞书推个消息、随手 import 一下,环就成了;而循环依赖不会立刻报错,它只是逼着后来人到处写函数内延迟导入,
直到某天导入顺序一变就炸。曾经就出现过 domain.agent.confirmations ⇄ integrations.feishu.service 这一个环
(领域层回调集成层),靠把推送挪到路由层解掉。

**延迟导入不是分层的解法** —— 为绕环而延迟只是把环藏进调用那一刻(模块图里那条边还在),判据写在
`test_下层不认识上层`:两边互相引用永远说明有个东西站错了地方,正解是把它**下沉到叶子模块**。
仍然允许的是「真的运行时才需要、且加载代价高」,那一条的说明里给了仓库里的真实例子与两者的分界。
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

#: 这份文件是一道**棘轮**:反向依赖一条都不许有;算上函数内的延迟导入,模块级、包级的环也一个都不许有。
RATCHET = True

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

    顶层 import 是**加载时的绑定**:它把两层焊死,代价是 import 一个底层模块就要把上层整棵拉起来,而那恰恰
    是让循环依赖有机可乘的形状。

    **函数内的延迟导入不是这一条的解法。** 为了让这条棘轮不红而把 import 挪进函数体,只是把那个环藏起来:
    模块图里那条边照样在(文件末尾那两条棘轮建图时把函数体内的 import 也算上,就是这个道理),代价换成了
    调用那一刻才炸、而且成不成看导入顺序 —— 直到某天一条毫不相干的路径上报出
    `ImportError: cannot import name ... (most likely due to a circular import)`。

    **正解是下沉。** 两边互相引用,永远说明有个东西站错了地方(和 `docs/CONVENTIONS.md` 里那条前端的同名
    规矩同一条:「通用工具放 `lib/` 或 `components/`,属于某个领域的东西放回它的领域」):把两边都要的那个
    东西挪到**叶子模块**去 —— 它只认识标准库或更下面的模块,谁也不认识上层,于是那条边从「反向」变成
    「向下」。这套代码库一直这么做:引擎与执行器之间只有 `executors/registry.py` 一个面、`convert.type_of`
    从 `workflow_import` 搬到了只依赖 `lines` 的 `convert`、插件那三个两模块环各自下沉成
    `layouts` / `civitai_urls` / `tool_registry`。

    **仍然允许的是「真的运行时才需要」** —— 那条路径本来就会用到它,而加载它的代价很高:几百 MB 的子进程
    依赖(`ai/runtime/workers/asr.py` 的 `import whisperx`、`tts.py` 的 `from f5_tts.api import F5TTS` 与两处
    `import torch` —— 都只在那个专用解释器里用)、可选依赖、平台兜底。
    **两者的分界不在写在哪儿,而在为什么写在那儿**:说得出「用到它的那条路径之外不必付这个代价」是前者;
    答不上来、只知道挪进去棘轮就不红了,就是后者 —— 后者该下沉,不该延迟。
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
        "下层在**顶层** import 了上层。挪进函数体不解决这件事 —— 那只是把环藏起来(模块图里那条边还在,"
        "换成调用那一刻才炸、且成不成看导入顺序)。正解是**下沉**:把两边都要的那个东西挪到一个叶子模块"
        "(只认识标准库或更下面的模块),两边都从那里取。只有「真的运行时才需要、且加载代价高」才留在函数体"
        "(判据见这条测试的说明):\n  " + "\n  ".join(sorted(violations))
    )


def test_领域连延迟导入也不认识集成层() -> None:
    """**这一条连函数内的延迟导入也不放过。**

    上一条只给「真的运行时才需要、且加载代价高」留了口子(分界写在那里)。领域层对集成层没有这样的场合:
    领域要的外部能力经 ai/providers 的公共入口拿,集成层(飞书这类)是**调用领域的一方**。此前唯一的一处是
    引擎目录延迟 import integrations.volc_openapi 去拉火山账号的音色 —— 那是「怎么跟火山说话」,已经搬进
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


def test_no_cycle_survives_even_lazy_imports() -> None:
    """把函数内的延迟导入也算上,模块之间**一个环都不许有**。

    函数内 import 绕开的只是**导入期**的报错:两个模块照样互相认识,改一边就得懂另一边。这里曾经冻结过
    三十一个模块(TTS 引擎目录与语言表、插件实例与工具调用、生成解析与供应商模型、工作流引擎与执行器),
    每一族都是一个职责放错了层:F5 权重的挑法住在引擎目录里、清单的读法住在实例里、静态生成目录住在生成域里、
    「再跑一张图」写死成 import 引擎。挪到该在的那一层(或换成组装根接上的一道缝)之后,清单清空、规则收紧。

    更早还允许过一个:core.db ⇄ db.models —— Base 定义在 core.db,models 依赖它,而 init_db 又要回头
    import models 才能 create_all,当时判成"SQLAlchemy 的标准形态,无法消除"。**那个判断是错的**:环的根源
    不是 Base,是 `core/db.py` 同时当了底座和迁移编排器。

    红了的话:**不要**再写一个函数内的 import 绕过去,那正是这条要拦的。看是哪条边往回走 ——
    多半是一个只该住在下层的东西(一张词表、一份静态目录)放在了上层,或者下层在替上层做事;前者挪下去,
    后者在下层开一道缝(`on_xxx` / `use(...)`),由组装根 `app.main._wire_seams` 接上。
    """
    cycles = _cycles(_graph(include_lazy=True))
    assert not cycles, "这些模块(算上函数内的延迟导入)互相 import:\n  " + "\n  ".join(" ⇄ ".join(c) for c in cycles)


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


def test_packages_stay_acyclic_even_lazily() -> None:
    """包级,算上函数内的延迟导入:领域包之间也**一个环都不许有**。

    模块级无环挡不住这一种:素材删除回头问发布、素材导入回头起文档解析、资产补画回头跑工作流执行器 ——
    没有哪两个**模块**首尾相接,十四个包却连成了一个环。拆法见各处:素材域开了删除与入库的缝(assets.deletion /
    assets.importer),补画挪进工作流域(workflows.entity_drawing),授权声明的词表成了叶子(domain/consent),
    静态生成目录挪出生成域(domain/generation_catalog)。
    """
    cycles = _cycles(_package_graph(include_lazy=True))
    assert not cycles, "这些包(算上函数内的延迟导入)互相 import:\n  " + "\n  ".join(" ⇄ ".join(c) for c in cycles)
