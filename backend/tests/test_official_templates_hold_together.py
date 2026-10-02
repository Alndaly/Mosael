"""官方模板建出来的图:画布上看到的连线,就是引擎真正等的先后和真正会跑的节点。

TEMPLATE_CATALOG 里的每一个(整片、业务、译配、整理、分析)都过下面这几条。

## 现场

- 「从主题到完整视频」的「可用的 3D 道具」在模板里一条连线都没有,只靠布景提示词里的 `{{props.catalog}}` 引用。
  引用即依赖只管先后,不管该不该跑:顶层没有入边的节点引擎不跑(engine.is_entry 只认开始节点),编辑器上挂着
  「未连接到流程」的角标,布景师拿到的道具清单永远是空的 —— 从它加进模板那一版起就没跑过。
- 同一张图里「按画幅取尺寸 → 建项目」「建项目 → 三视图 / 设定图」只写在引用里:引擎照样等,画布上看不见。
- 规范化把「配字幕」那条带数据的控制边折掉,出镜版带货口播收尾为空时字幕、导出整段被跳过,照样报成功。

每一处都是「图本身没问题、单看哪个函数都对」,只有把整张图摆出来逐条核对才看得见。

## 守的几条

1. 除开始节点外,顶层每个节点都可能跑:从开始节点沿着「决定它跑不跑」的连线走得到 —— 运行前检查与编辑器就绪检查的
   disconnected 同一个判据(graph_rules.never_run_nodes / analyze.ts 的 neverRunNodes,契约
   contracts/workflow-never-run-cases.json)。没有哪个会跑的节点引用了一定不会跑的节点(那是运行前的阻断)。
2. 两头都一定会跑的引用,画布上沿连线也是上游:谁等谁,看图就知道。条件分支里可能不跑的不算 —— 那种引用
   (「另一支没跑,引用出来是空串」)是作者有意的,画成控制边反倒会改谁该跑。
3. 就绪:落库前的结构校验干净;运行前的校验除了留给用的人填的那几格(必填、几选一),没有别的阻断;数据边两头的
   类型对得上(编辑器的 type-mismatch 同一个判据)。
4. 规范化折掉的控制边不改谁该跑(另有路由边说了算的除外 —— 作者画那几条就是为了排先后)。
5. 新建、按新版重建、官网副本:节点和连线一模一样。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import importlib
import json
from copy import deepcopy
from typing import Any

import pytest

from app.domain.workflows import (
    NODE_TYPES,
    config_data_type,
    never_run_nodes,
    never_run_references,
    output_data_type,
    reference_dependencies,
    validate_graph,
    with_run_params,
)
from app.domain.workflows.field_activation import config_field_active
from app.domain.workflows.graph_rules import blank
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates import TEMPLATE_CATALOG, blank_template_graphs
from tests.util import fresh_client

TEMPLATE_IDS = [card["id"] for card in TEMPLATE_CATALOG]


def _created(template_id: str) -> tuple[Any, str, dict[str, Any]]:
    """走真的建图那条路(POST /workflows 带 template_id):建图函数、规范化、落库前的校验,一样不少。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    response = client.post("/api/workflows", json={"workspace_id": workspace, "name": template_id, "template_id": template_id})
    assert response.status_code == 200, response.text
    return client, workspace, response.json()


def _routing(edge: dict[str, Any], types: dict[str, str]) -> bool:
    """带路由语义的控制边:写了 handle,或从会分支的节点出发(没写 handle 也是「真」那一支)。"""
    return edge.get("kind", "control") == "control" and (
        bool(edge.get("source_handle")) or bool(NODE_TYPES[types[edge["source"]]].get("branches"))
    )


def _always_runs(graph: dict[str, Any]) -> set[str]:
    """一定会跑的节点(不算失败):engine.incoming_active 的判法,只是把条件分支一律当成可能不走 ——
    有控制边的,任一条不带路由的控制边来自一定会跑的节点;一条控制边都没有的,任一条数据边来自一定会跑的节点。"""
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    always = {node_id for node_id, node_type in types.items() if node_type == "start"}
    grew = True
    while grew:
        grew = False
        for node_id in types.keys() - always:
            incoming = [edge for edge in graph["edges"] if edge["target"] == node_id]
            control = [edge for edge in incoming if edge.get("kind", "control") == "control"]
            deciding = [edge for edge in control if not _routing(edge, types)] if control else incoming
            if any(edge["source"] in always for edge in deciding):
                always.add(node_id)
                grew = True
    return always


def _upstream(graph: dict[str, Any]) -> dict[str, set[str]]:
    """每个节点沿连线的全部上游。"""
    predecessors: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        predecessors.setdefault(edge["target"], set()).add(edge["source"])
    found: dict[str, set[str]] = {}

    def walk(node_id: str) -> set[str]:
        if node_id not in found:
            found[node_id] = set()
            for source in predecessors.get(node_id, ()):
                found[node_id] |= {source} | walk(source)
        return found[node_id]

    return {node["id"]: walk(node["id"]) for node in graph["nodes"]}


def _filled_in(graph: dict[str, Any]) -> dict[str, Any]:
    """把留给用的人填的格子(必填、几选一 —— 挑素材、挑模型、挑音色、确认授权……,循环体里的也算)当成他填好了。
    剩下的阻断就都不是他该填的:失效引用、开始节点没有的参数、环、未知类型、体里的作用域……"""
    filled = deepcopy(graph)

    def fill(layer: dict[str, Any]) -> None:
        bound = {(edge["target"], edge.get("target_input")) for edge in layer["edges"] if edge.get("kind") == "data"}
        for node in layer["nodes"]:
            config = node.setdefault("config", {})
            specs = NODE_TYPES[node["type"]]["config"]
            groups: dict[str, list[str]] = {}
            for key, spec in specs.items():
                if not isinstance(spec, dict) or (node["id"], key) in bound or not config_field_active(spec, config, specs):
                    continue
                if spec.get("required") and blank(config.get(key)):
                    config[key] = "用的人填的"
                if spec.get("one_of"):
                    groups.setdefault(spec["one_of"], []).append(key)
            for keys in groups.values():
                if all(blank(config.get(key)) and (node["id"], key) not in bound for key in keys):
                    config[keys[0]] = "用的人填的"
            body = config.get("body")
            if isinstance(body, dict) and isinstance(body.get("nodes"), list):
                fill(body)

    fill(filled)
    return filled


def _run_params(graph: dict[str, Any]) -> dict[str, str]:
    start = next(node for node in graph["nodes"] if node["type"] == "start")
    names = str(start["config"].get("required_params") or "").replace("，", ",").split(",")
    return {name.strip(): "跑的人填的" for name in names if name.strip()}


def _data_type(value: Any) -> str:
    return value if value in {"text", "asset", "sequence", "number", "json", "any"} else "any"


def _type_mismatches(graph: dict[str, Any]) -> list[str]:
    """数据边两头的类型对不上 —— analyze.ts 的 type-mismatch(typesCompatible)同一个判据,连同循环体里的。"""
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    found = []
    for edge in graph["edges"]:
        if edge.get("kind") != "data":
            continue
        source_meta, target_meta = NODE_TYPES[types[edge["source"]]], NODE_TYPES[types[edge["target"]]]
        actual = _data_type(output_data_type(edge["source_output"], source_meta))
        expected = _data_type(config_data_type(edge["target_input"], target_meta["config"].get(edge["target_input"], {})))
        if not (expected in ("any", "text") or actual == "any" or actual == expected):
            found.append(f"{edge['source']}.{edge['source_output']}({actual}) → {edge['target']}.{edge['target_input']}({expected})")
    for node in graph["nodes"]:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            found += [f"{node['id']} › {one}" for one in _type_mismatches(body)]
    return found


def _shape(graph: dict[str, Any]) -> dict[str, Any]:
    """节点(id、类型)和连线,连同循环体里的 —— 「是不是同一张图」只看这些(名字、配置、位置另说)。"""
    nodes = []
    for node in graph["nodes"]:
        body = (node.get("config") or {}).get("body")
        inner = _shape(body) if isinstance(body, dict) and isinstance(body.get("nodes"), list) else None
        nodes.append((node["id"], node["type"], json.dumps(inner, sort_keys=True)))
    edges = sorted(json.dumps(edge, sort_keys=True) for edge in graph["edges"])
    return {"nodes": sorted(nodes), "edges": edges}


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_除开始节点外每个顶层节点都可能跑(template_id: str) -> None:
    _, _, created = _created(template_id)
    assert never_run_nodes(created["graph"]) == set(), "顶层没有入边的节点引擎不跑(engine.is_entry 只认开始节点)"


def _never_run_references_in_every_layer(graph: dict[str, Any], where: str = "", *, entry_is_root: bool = False) -> list[str]:
    found = [f"{where}{one}" for one in never_run_references(graph, entry_is_root=entry_is_root)]
    for node in graph["nodes"]:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            found += _never_run_references_in_every_layer(body, f"{where}{node['id']} › ", entry_is_root=True)
    return found


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_没有会跑的节点引用一定不会跑的节点_运行前不会被这一条拦(template_id: str) -> None:
    """「可用的 3D 道具」那种:引用挂着、节点没接进流程。运行前检查拦的就是它(graph_rules.never_run_references),
    官方模板建出来的图一处都不能有 —— 循环体、子图里按它们自己的入口规则,一样查。"""
    _, _, created = _created(template_id)
    assert _never_run_references_in_every_layer(created["graph"]) == []


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_两头都一定会跑的引用_画布上沿连线也是上游(template_id: str) -> None:
    graph = _created(template_id)[2]["graph"]
    always, upstream = _always_runs(graph), _upstream(graph)
    hidden = sorted(
        f"{source} → {target}"
        for target, sources in reference_dependencies(graph).items()
        for source in sources
        if source in always and target in always and source not in upstream[target]
    )
    assert hidden == [], "引擎等着它们,画布上却看不出谁在谁前面"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_就绪检查只等用的人填那几格_没有别的阻断和警告(template_id: str) -> None:
    graph = _created(template_id)[2]["graph"]
    assert validate_graph(graph, require_config=False) == [], "落库前的结构校验"
    assert validate_graph(with_run_params(_filled_in(graph), _run_params(graph))) == [], "运行前的校验"
    assert _type_mismatches(graph) == []


def _raw_template_graphs(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """建图函数最后都过一遍 normalize_graph;换成原样交回,拿到的就是作者画的那张(规范化之前)。"""
    for name in ("templates_full_video", "templates_business", "templates_analysis", "templates_cleanup", "templates_dub"):
        module = importlib.import_module(f"app.domain.workflows.{name}")
        monkeypatch.setattr(module, "normalize_graph", lambda graph, *, node_types: graph)
    return blank_template_graphs("zh")


def _who_decides(graph: dict[str, Any]) -> dict[str, tuple[str, frozenset[tuple[str, str]]]]:
    """每个节点「该不该跑」看哪几条入边(engine.incoming_active):有控制边只看控制边(带路由的记下要哪一支),
    没有就看数据边。"""
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    decided = {}
    for node_id in types:
        incoming = [edge for edge in graph["edges"] if edge["target"] == node_id]
        control = [edge for edge in incoming if edge.get("kind", "control") == "control"]
        terms = frozenset(
            (edge["source"], (edge.get("source_handle") or "true") if _routing(edge, types) else "")
            for edge in (control or incoming)
        )
        decided[node_id] = ("control" if control else "data", terms)
    return decided


def _folds_that_change_who_runs(raw: dict[str, Any], normalized: dict[str, Any], where: str) -> list[str]:
    types = {node["id"]: node["type"] for node in raw["nodes"]}
    before, after = _who_decides(raw), _who_decides(normalized)
    changed = [
        f"{where}{node_id}: {sorted(before[node_id][1])} → {sorted(after[node_id][1])}"
        for node_id in before
        if before[node_id][1] != after[node_id][1]
        and not any(edge["target"] == node_id and _routing(edge, types) for edge in raw["edges"])
    ]
    inner = {node["id"]: node for node in normalized["nodes"]}
    for node in raw["nodes"]:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            changed += _folds_that_change_who_runs(body, inner[node["id"]]["config"]["body"], f"{where}{node['id']} › ")
    return changed


def test_规范化折掉的控制边不改谁该跑(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _raw_template_graphs(monkeypatch)
    assert set(raw) == set(TEMPLATE_IDS)
    changed = {
        template_id: _folds_that_change_who_runs(graph, normalize_graph(graph, node_types=NODE_TYPES), "")
        for template_id, graph in raw.items()
    }
    assert {template_id: one for template_id, one in changed.items() if one} == {}


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_新建_按新版重建_官网副本是同一张图(template_id: str) -> None:
    client, workspace, created = _created(template_id)
    #: 一张「旧版」:版本号低一版,还少一条连线(旧版模板里没有的那种),重建出来的照样是现行这一张。
    old = deepcopy(created["graph"])
    old["meta"]["template_version"] -= 1
    old["edges"] = old["edges"][1:]
    saved = client.post("/api/workflows", json={"workspace_id": workspace, "name": "旧版", "graph": old})
    assert saved.status_code == 200, saved.text
    rebuilt = client.post(f"/api/workflows/{saved.json()['id']}/rebuild-from-template")
    assert rebuilt.status_code == 200, rebuilt.text
    assert _shape(rebuilt.json()["graph"]) == _shape(created["graph"])
    #: 卡片上写明了下载的那份不一样(download_note:上身图那份带着视频那一步,应用里按有没有视频模型取舍)的除外。
    if "download_note" not in next(card for card in TEMPLATE_CATALOG if card["id"] == template_id):
        assert _shape(blank_template_graphs("zh")[template_id]) == _shape(created["graph"]), "官网副本"
