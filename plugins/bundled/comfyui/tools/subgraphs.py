"""界面格式的图里,**子图**是怎么套的:哪几份定义、每份被哪几个节点用着、`12:5` 这种写法指到哪个节点。

这是最底下的一层 —— 只认「图」这个数据形状(节点、`type` 是某份定义的 id、`definitions.subgraphs`),不查 ComfyUI、不认识
节点类型、不 import 别的模块:好几处都要用它(画布摘要、诊断、模板、应用表单的标记),而它们各自还带着别的依赖,放在
`canvas.py` 里会绕成环(`app_form` → `canvas` → `workflow_library` → `models` → `app_form`)。

**节点怎么指**:根图上的节点就是它的编号(`12`);子图里的节点用 ComfyUI 执行时的写法 —— 从根图往里走的节点号,冒号隔开
(`12:5` 是根图 12 号节点那个子图里面的 5 号)。这是 ADR 0042 那一套,画布摘要、`convert`、插件的定位、应用表单的标记,
说的都是它。
"""

from __future__ import annotations

from typing import Any

#: 子图套得再深也只走这么多层(坏文件可能套了它自己)。
MAX_DEPTH = 16


def definitions(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """子图定义:id → 那一份(套在定义里的定义也收)。"""
    found: dict[str, dict[str, Any]] = {}

    def collect(scope: dict[str, Any], depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        for one in ((scope.get("definitions") or {}).get("subgraphs") or []):
            if isinstance(one, dict) and one.get("id") and str(one["id"]) not in found:
                found[str(one["id"])] = one
                collect(one, depth + 1)

    collect(graph, 0)
    return found


def nodes_of(scope: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in scope.get("nodes") or [] if isinstance(node, dict) and node.get("id") is not None]


def instance_paths(graph: dict[str, Any]) -> dict[str, list[str]]:
    """每份子图定义在这张图里被哪几个节点用着:从根图往里走的节点号路径(`12`、`12:5`),按先后。"""
    defs = definitions(graph)
    found: dict[str, list[str]] = {}

    def walk(scope: dict[str, Any], prefix: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        for node in nodes_of(scope):
            kind = str(node.get("type") or "")
            if kind in defs:
                path = f"{prefix}{node['id']}"
                paths = found.setdefault(kind, [])
                if path not in paths and len(paths) < 50:
                    paths.append(path)
                    walk(defs[kind], f"{path}:", depth + 1)

    walk(graph, "", 0)
    return found


def locate_ref(graph: dict[str, Any], ref: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`12:5` → (那一层子图定义(根图上的是 None), 节点)。指不到 → (None, None)。"""
    defs = definitions(graph)
    parts = str(ref or "").split(":")
    scope: dict[str, Any] = graph
    layer: dict[str, Any] | None = None
    for depth, part in enumerate(parts):
        node = next((one for one in nodes_of(scope) if str(one["id"]) == part), None)
        if node is None:
            return None, None
        if depth == len(parts) - 1:
            return layer, node
        layer = defs.get(str(node.get("type") or ""))
        if layer is None:
            return None, None
        scope = layer
    return None, None


__all__ = ["MAX_DEPTH", "definitions", "instance_paths", "locate_ref", "nodes_of"]
