"""作者画出来的控制边,**规范化一条都不许折**:官方模板沿控制边从开始走得到交付。

## 现场(2026-10-16 全模板只读审计)

15 张官方模板里作者手写的图,`start → output` 的控制链**本来都完整(15/15)**。是规范化
(`normalization.canonicalize_data_bindings`)把它折了:模板用精确引用 `{{节点.输出}}` 写取值,规范化把引用
升级成显式数据边之后,顺手把同一对节点间「只排先后」的控制边当多余的折掉(数据边也排先后)。

结果:**10/15 张**控制链断、**68 条**控制边被折、**55 个**节点只剩数据入边(画布上那一格没有线)。
折与不折还取决于目标当时有没有别的入边 —— 「谁该跑」不变才折,于是同一张图里时有时无。

折边当初的借口是「引擎只看控制边,折了谁该跑也不变」;可它**确实会变** —— 目标上有条件的真 / 假出口时,
那几条只排先后的边折掉,门才生效(出镜版带货口播「开场那句是空的就跳过出镜」就是这么来的)。所以
`engine.incoming_active` 现在把这条判法明说(带路由语义的控制边说了算;与同向数据线重复的普通控制边只排
先后,不激活),折与不折「谁该跑」因此完全一样。但**画出来的边曾经没了**:维护者要的是「画布上看到的连线,
就是这张图」。所以画出来的控制边一律保留(见 docs/adr/0063-画出来的控制边一律保留.md)。

这两条是棘轮:少了任何一条控制边、或 `start` 沿控制边走不到 `output`,就红。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import importlib
from collections import Counter
from typing import Any, Iterator

import pytest

from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates import TEMPLATE_CATALOG, blank_template_graphs
from tests.util import fresh_client

TEMPLATE_IDS = [card["id"] for card in TEMPLATE_CATALOG]

#: 模板建图函数最后一步都过 normalize_graph;把它换成原样交回,拿到的就是作者画的那一张(和
#: test_official_templates_hold_together 取原图同一条路 —— 规范化之前 vs 之后,用的是同一个函数)。
_TEMPLATE_MODULES = (
    "templates_full_video",
    "templates_business",
    "templates_analysis",
    "templates_cleanup",
    "templates_dub",
    "templates_shots",
)


def _created(template_id: str) -> dict[str, Any]:
    """走真的建图那条路(POST /workflows 带 template_id):建图、规范化、落库,一样不少。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    response = client.post(
        "/api/workflows", json={"workspace_id": workspace, "name": template_id, "template_id": template_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["graph"]


def _raw_graphs(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    for name in _TEMPLATE_MODULES:
        module = importlib.import_module(f"app.domain.workflows.{name}")
        monkeypatch.setattr(module, "normalize_graph", lambda graph, *, node_types: graph)
    return blank_template_graphs("zh")


def _layers(graph: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """这一层,连同它所有嵌套体(循环体 / 子图) —— 一层一层按同一个顺序走,原图与规范图可以对着比。"""
    yield graph
    for node in graph.get("nodes") or []:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            yield from _layers(body)


def _control_wires(graph: dict[str, Any]) -> Counter[tuple[str, str, str]]:
    """这一层作者画的控制边:来源、去向、走哪一支(没写 handle 就是没写)。数据边不算。"""
    return Counter(
        (str(edge.get("source", "")), str(edge.get("target", "")), str(edge.get("source_handle") or ""))
        for edge in graph.get("edges") or []
        if edge.get("kind", "control") == "control"
    )


def _data_wires(graph: dict[str, Any]) -> Counter[tuple[str, str, str, str]]:
    return Counter(
        (str(edge.get("source", "")), str(edge.get("source_output", "")),
         str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in graph.get("edges") or []
        if edge.get("kind") == "data"
    )


def _reachable_over_control(graph: dict[str, Any], start: str) -> set[str]:
    """沿**控制边**从开始节点走得到的节点 —— 画布上那条链。条件分支两支都算走得到(和画布的判据一致)。"""
    control = {}
    for edge in graph.get("edges") or []:
        if edge.get("kind", "control") == "control":
            control.setdefault(str(edge.get("source", "")), set()).add(str(edge.get("target", "")))
    seen, queue = {start}, [start]
    while queue:
        for target in control.get(queue.pop(), ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_每张官方模板_沿控制边从开始走得到交付(template_id: str) -> None:
    """`start → output` 的控制链必须完整:画出来的先后,就是画布上看得见的那条链。"""
    graph = _created(template_id)
    start = next(node["id"] for node in graph["nodes"] if node["type"] == "start")
    outputs = [node["id"] for node in graph["nodes"] if node["type"] == "output"]
    assert len(outputs) == 1, f"顶层该正好有一个交付节点,现在是 {outputs}"
    reachable = _reachable_over_control(graph, start)
    assert outputs[0] in reachable, (
        f"沿控制边从 {start} 走不到 {outputs[0]};控制边能走到的顶层节点:{sorted(reachable)}"
    )


def test_规范化前后_作者画的控制边一条不少(monkeypatch: pytest.MonkeyPatch) -> None:
    """规范化只许**加**边(精确引用升级出来的数据边),不许动作者画的控制边 —— 一条都不少。"""
    raw = _raw_graphs(monkeypatch)
    assert set(raw) == set(TEMPLATE_IDS)
    folded: dict[str, list[str]] = {}
    lost_data: dict[str, list[str]] = {}
    for template_id, graph in raw.items():
        normalized = normalize_graph(graph, node_types=NODE_TYPES)
        for index, (before, after) in enumerate(zip(_layers(graph), _layers(normalized))):
            gone = _control_wires(before) - _control_wires(after)
            where = f"第 {index} 层" if index else "顶层"
            if gone:
                folded.setdefault(template_id, []).extend(
                    f"{where}: {source} → {target}" + (f" ({handle})" if handle else "")
                    for source, target, handle in sorted(gone.elements())
                )
            missing = _data_wires(before) - _data_wires(after)
            if missing:
                lost_data.setdefault(template_id, []).extend(
                    f"{where}: {source}.{output} → {target}.{input}" for source, output, target, input in sorted(missing.elements())
                )
    assert folded == {}, f"规范化折掉了作者画的控制边({sum(len(one) for one in folded.values())} 条)"
    assert lost_data == {}, "规范化丢了本来就有的数据边 —— 精确引用的升级只有加,没有减"
