"""结构性约束:**插件自己的 import 图没有环**(`plugins/bundled/comfyui/tools`,顶层与函数体内的 import 一起算)。

ComfyUI 插件是一包平铺的模块(`tools/*.py`),按顶层名字互相 import。放它进棘轮是因为它此前有三个两模块的
环,而每个环都只由**一条**函数内的延迟导入撑着 —— 分层那条棘轮只管后端 `app.*`,看不到这里:

| 环 | 撑着它的那条 |
| --- | --- |
| `shared_models ⇄ service` | `shared_models` 函数内 `import service`,只为 `find_layout` |
| `civitai ⇄ sources` | `sources` 函数内 `import civitai`,只为版本号与那个版本的信息 |
| `tooling ⇄ workflows` | `tooling` 函数内 `from workflows import deliver`;而 `workflows` 顶层借 `tooling` 的 `tool_names` / `runnable` / `output_key` |

三个都按同一条处方拆掉 —— **把两边都要的那个东西下沉成叶子模块**,不是把 import 挪进函数体(那样只是把环
藏到调用那一刻):

- `layouts.py`:`Layout` / `find_layout` / `LAYOUT_LABELS`(纯认目录 + 一张表);
- `civitai_urls.py`:`page` / `version_id_of`(纯解析地址);「哪个站上的哪一页」那一步搬进 `provenance`
  —— 它要问 Civitai 的接口,而 `civitai` 又要从 `sources` 出网;
- `tool_registry.py`:工具名的读面(`tool_names` / `runnable` / `output_key` / `safe` / `short_hash` /
  `path_name`),`tooling` 与 `workflows` 都从这里取。

拆完**顶层图 0 环、连函数体内的 import 算上也是 0 环**。`LAZY_CYCLE_MODULES` 是那份只减不增的账本:
它现在空着,而上面那三个环曾经就冻结在里面。
"""

from __future__ import annotations

#: 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import collections
from pathlib import Path

from tests.test_import_layering import _cycles

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"


def _modules() -> list[tuple[str, Path]]:
    """插件这一包是平铺的:一个文件一个顶层模块(没有包、没有相对导入)。"""
    return [(path.stem, path) for path in sorted(TOOLS.glob("*.py")) if path.name != "__init__.py"]


def _graph(include_lazy: bool) -> dict[str, set[str]]:
    """插件内部模块的依赖图。

    判据和后端那条分层棘轮同一套(见 `test_import_layering._graph`):`from lines import ComfyError` 拉进来的
    是 `lines` 这个模块,不是 `ComfyError`。这里的模块名是平铺的,所以取第一段。
    """
    mods = _modules()
    known = {name for name, _ in mods}

    def targets_of(node: ast.Import | ast.ImportFrom) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        base = node.module or ""
        return [f"{base}.{alias.name}" if f"{base}.{alias.name}" in known else base for alias in node.names]

    graph: dict[str, set[str]] = collections.defaultdict(set)
    for name, path in mods:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        inner: set[int] = set()
        if not include_lazy:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner.update(id(sub) for sub in ast.walk(node))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or (not include_lazy and id(node) in inner):
                continue
            for dotted in targets_of(node):
                hit = dotted.split(".")[0]
                if hit in known and hit != name:
                    graph[name].add(hit)
    return graph


def test_插件的顶层导入无环() -> None:
    """只看顶层 import:插件的模块图必须无环 —— 顶层成环意味着 import 顺序决定成败。"""
    assert not _cycles(_graph(include_lazy=False))


#: 算上函数内的延迟导入之后**还在环里的插件模块**。只减不增的棘轮,规则同后端的 LAZY_CYCLE_MODULES。
#:
#: 它空着不是一直如此:此前冻结着 `service` / `shared_models`、`civitai` / `sources`、`tooling` / `workflows`
#: 这六个模块(三个两模块的环,各自由一条函数内 import 撑着,见模块说明)。新模块进环 → 红;有模块出了环 →
#: 也红,把它从这里删掉(不留一扇随时可以走回来的门)。
LAZY_CYCLE_MODULES: frozenset[str] = frozenset()


def test_插件的环只减不增() -> None:
    """把函数内的延迟导入也算上,环里的模块**只减不增**(见 LAZY_CYCLE_MODULES)。

    延迟导入在插件里不是分层的解法:它只是把环藏进调用那一刻 —— 模块图里那条边还在。要新添一个环,先回答
    「两边都要的那个东西为什么不能住在下面」;答不上来就把它下沉成叶子模块。
    """
    in_cycles = {module for cycle in _cycles(_graph(include_lazy=True)) for module in cycle}
    joined = sorted(in_cycles - LAZY_CYCLE_MODULES)
    assert not joined, (
        "这些插件模块新进了循环依赖(通常是某处用函数内 import 绕开了分层 —— 正解是下沉共用的那个东西):\n  "
        + "\n  ".join(joined)
    )
    left = sorted(LAZY_CYCLE_MODULES - in_cycles)
    assert not left, "这些模块已经不在环里了,把它们从 LAZY_CYCLE_MODULES 里删掉:\n  " + "\n  ".join(left)
