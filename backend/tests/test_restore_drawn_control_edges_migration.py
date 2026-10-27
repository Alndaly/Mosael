"""旧图里**被规范化折掉**的控制边,由迁移自己从旧数据里补回来。

## 现场

2026-10-02 到 2026-10-16 之间,规范化把作者画的、同一对节点间已经/即将有一条数据边的无 handle 控制边
当多余的折掉(`normalization.canonicalize_data_bindings` 的 `redundant()`)。维护者 2026-10-16 拍板
不再折(ADR 0063),**可库里已经存下的图不会自己长回来** —— 规范化只加数据边、从不凭空补控制边。
老图打开再存一遍还是缺线那样子。所以补线要一条迁移(`db/migrations._migrate_restore_drawn_control_edges`),
判据在领域层 `graph_upgrade.drawn_control_edges_come_back`(e35979a10^ 折边判据的只读复刻)。

## 这条测试在证什么

**「等价性」:作者画的图 ⇒ 旧规范化 ⇒ 旧数据 ⇒ 新迁移,要回到作者画的那张。** 15 张官方模板各来一遍。

折掉的边**连 id 都没留下**(规范化只认「一对节点」,不认那条边叫什么),所以比的是**边本身**
(来源、去向、走哪一支)与「同一个 id 不许被改成别的边」,这是这个仓库里「作者画的边一条不少」的既有口径
(见 tests/test_drawn_control_edges_are_never_folded.py)。

**两种作者画法落库是同一个样子**(`test_两种作者画法落库是同一个样子`):画了 S→T 被折掉,和压根没画 S→T、
只是把 `{{S.输出}}` 写进 T 的配置 —— 旧数据里分不出来(官方模板里这种「只是写了引用」的对子有 60 处)。
能证的只有一种形状:**T 一条控制入边都没有**;T 另外还有普通控制入边、或有条件的真 / 假出口时,当年折没折
分不出来(那里一条都不补)。所以下面两条断言分工明确:

- `test_迁移把折掉的作者控制边补回来`:一条**不凭空造**(补的每一条作者都画过),少的只有「证不出」的那些,
  而且补完 15 张模板沿控制边都从开始走得到交付 —— 这正是维护者要的那件事;
- `test_证得出的旧图_迁移之后与作者画的一模一样`:把「证不出」的那几条从作者的图里去掉(那本来就是
  「作者没画」的样子),迁移结果与作者画的那张**逐条一致** —— 迁移之前是缺边的(这条测试在旧实现上先红)。
"""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from typing import Any, Iterator

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import User, Workflow
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.engine import BRANCHING_NODE_TYPES
from app.domain.workflows.graph_upgrade import drawn_control_edges_come_back
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.revisions import commit_graph_revision, graph_digest
from app.domain.workflows.templates import TEMPLATE_CATALOG, blank_template_graphs
from tests.util import fresh_client

TEMPLATE_IDS = [card["id"] for card in TEMPLATE_CATALOG]

#: 模板建图函数最后一步都过 normalize_graph;把它换成原样交回,拿到的就是作者画的那一张
#: (和 tests/test_drawn_control_edges_are_never_folded.py 取原图同一条路)。
_TEMPLATE_MODULES = (
    "templates_full_video",
    "templates_business",
    "templates_analysis",
    "templates_cleanup",
    "templates_dub",
    "templates_shots",
)


def _raw_graphs(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    for name in _TEMPLATE_MODULES:
        module = importlib.import_module(f"app.domain.workflows.{name}")
        monkeypatch.setattr(module, "normalize_graph", lambda graph, *, node_types: graph)
    return blank_template_graphs("zh")


def _layers(graph: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """这一层,连同它所有嵌套体(循环体 / 子图)。"""
    yield graph
    for node in graph.get("nodes") or []:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            yield from _layers(body)


def _control_wires(graph: dict[str, Any]) -> list[tuple[str, str, str]]:
    """全层级的控制边:来源、去向、走哪一支(没写 handle 就是没写)。数据边不算。"""
    return sorted(
        (str(edge.get("source", "")), str(edge.get("target", "")), str(edge.get("source_handle") or ""))
        for layer in _layers(graph)
        for edge in layer.get("edges") or []
        if edge.get("kind", "control") == "control"
    )


def _data_wires(graph: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(edge.get("source", "")),
            str(edge.get("source_output", "")),
            str(edge.get("target", "")),
            str(edge.get("target_input", "")),
        )
        for layer in _layers(graph)
        for edge in layer.get("edges") or []
        if edge.get("kind") == "data"
    )


def _branches(nodes: dict[str, Any], node_id: str) -> bool:
    """来源节点会分支吗(条件的真 / 假出口)—— 当年 `routes()` 就是问这一格。"""
    return str((nodes.get(node_id) or {}).get("type", "")) in BRANCHING_NODE_TYPES


def _fold_layer(layer: dict[str, Any]) -> None:
    """这一层按 e35979a10^ 的 `redundant()` 折边(嵌套体由 `_stored_by_the_old_normalizer` 逐层调)。"""
    nodes = {str(node.get("id")): node for node in layer.get("nodes") or []}
    edges = layer.get("edges") or []
    data_sources: dict[str, set[str]] = {}
    upgraded_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.get("kind") != "data":
            continue
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        data_sources.setdefault(target, set()).add(source)
        if str(edge.get("id") or "").startswith("d-"):
            upgraded_pairs.add((source, target))
    control_into: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge.get("kind", "control") == "control":
            control_into.setdefault(str(edge.get("target", "")), []).append(edge)

    def routes(edge: dict[str, Any]) -> bool:
        return _branches(nodes, str(edge.get("source", "")))

    def ordering_only(edge: dict[str, Any]) -> bool:
        return (
            edge.get("kind", "control") == "control"
            and not edge.get("source_handle")
            and not routes(edge)
            and (str(edge.get("source", "")), str(edge.get("target", ""))) in upgraded_pairs
        )

    def routing(edge: dict[str, Any]) -> bool:
        return edge.get("kind", "control") == "control" and (bool(edge.get("source_handle")) or routes(edge))

    def foldable_into(target: str) -> bool:
        control = control_into.get(target, [])
        if any(routing(edge) for edge in control):
            return True
        return {str(edge.get("source", "")) for edge in control} == data_sources.get(target, set())

    layer["edges"] = [
        edge for edge in edges if not (ordering_only(edge) and foldable_into(str(edge.get("target", ""))))
    ]


def _stored_by_the_old_normalizer(graph: dict[str, Any]) -> dict[str, Any]:
    """作者画的图 → **当年落库的那张**:先规范化,再按 e35979a10^ 的 `redundant()` 把控制边折掉。

    折边那一段判据逐字取自 `git show e35979a10^:backend/app/domain/workflows/normalization.py`
    (`data_sources` / `upgraded_pairs` / `routes` / `ordering_only` / `routing` / `foldable_into` / `redundant`),
    只是搬到测试里当**造旧数据的夹具** —— 生产路径上那一段已经删掉,也不会再放回去(ADR 0063)。

    规范化这一步用**现在**的实现:它和旧实现的差别**只有**折边(见 48d4d79a9 与 e35979a10 的 diff),
    所以「现在的规范化 + 这里的折边」就是当年的落库结果。`upgraded_pairs`(`U`)在官方模板上等于
    「图里那些 `d-` 数据边的节点对」:原图一条 `d-` 边都没有,规范化这一趟升出来的数据边 id 就是
    规范化给它们的那个形状(`d-{来源}-{输出}-{目标}-{入参}`)。
    """
    stored = normalize_graph(deepcopy(graph), node_types=NODE_TYPES)
    for layer in _layers(stored):
        _fold_layer(layer)
    return stored


def _cases_the_rule_cannot_prove(graph: dict[str, Any]) -> set[tuple[str, str]]:
    """判据证不出的那些「缺一条控制边」:目标另有带路由语义的控制边。

    这种目标上,「作者画了 S→T 被折掉」和「作者没画 S→T、只是把 `{{S.输出}}` 写进了 T」在旧数据里是
    同一个样子 —— 折与不折「谁该跑」也一样(引擎有路由边时,与同向数据线重复的普通控制边只排先后),
    所以那里一条都不补,只在这里说清少的是哪些。
    """
    pairs: set[tuple[str, str]] = set()
    for layer in _layers(graph):
        nodes = {str(node.get("id")): node for node in layer.get("nodes") or []}
        data_sources: dict[str, set[str]] = {}
        routed: set[str] = set()
        for edge in layer.get("edges") or []:
            source, target = str(edge.get("source", "")), str(edge.get("target", ""))
            if edge.get("kind") == "data":
                data_sources.setdefault(target, set()).add(source)
            elif edge.get("kind", "control") == "control" and (
                edge.get("source_handle") or _branches(nodes, source)
            ):
                routed.add(target)
        for target in routed:
            pairs |= {(source, target) for source in data_sources.get(target, set()) if not _branches(nodes, source)}
    return pairs


def _reachable_over_control(graph: dict[str, Any], start: str) -> set[str]:
    control: dict[str, set[str]] = {}
    for layer in _layers(graph):
        for edge in layer.get("edges") or []:
            if edge.get("kind", "control") == "control":
                control.setdefault(str(edge.get("source", "")), set()).add(str(edge.get("target", "")))
    seen, queue = {start}, [start]
    while queue:
        for target in control.get(queue.pop(), ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _start_and_output(graph: dict[str, Any]) -> tuple[str, str]:
    start = next(str(node["id"]) for node in graph["nodes"] if node.get("type") == "start")
    output = next(str(node["id"]) for node in graph["nodes"] if node.get("type") == "output")
    return start, output


def _without_control_wires(graph: dict[str, Any], pairs: set[tuple[str, str]]) -> dict[str, Any]:
    """作者的那张图,去掉指定的控制边(`pairs` 是「证不出」的那些:作者没画的样子)。"""
    stripped = deepcopy(graph)
    for layer in _layers(stripped):
        layer["edges"] = [
            edge
            for edge in layer.get("edges") or []
            if edge.get("kind", "control") != "control"
            or (str(edge.get("source", "")), str(edge.get("target", ""))) not in pairs
        ]
    return stripped


def test_当年的折边折掉了作者画的控制边_这份旧数据符合当时的审计(monkeypatch: pytest.MonkeyPatch) -> None:
    """夹具本身要像当年的库:e35979a10 的审计说 15 张模板折掉 **68 条**、其中 **10 张**沿控制边走不到交付。"""
    raw = _raw_graphs(monkeypatch)
    assert set(raw) == set(TEMPLATE_IDS)
    folded_edges = 0
    broken: list[str] = []
    for template_id, graph in raw.items():
        stored = _stored_by_the_old_normalizer(graph)
        folded_edges += len(set(_control_wires(graph)) - set(_control_wires(stored)))
        start, output = _start_and_output(stored)
        if output not in _reachable_over_control(stored, start):
            broken.append(template_id)
    assert folded_edges == 68, f"当年折掉的条数对不上:现在是 {folded_edges}"
    assert len(broken) == 10, f"当年断链的模板数对不上:现在是 {len(broken)} 张 {sorted(broken)}"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_迁移把折掉的作者控制边补回来(template_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """旧数据 ⇒ 迁移:一条不凭空造、作者画过的一条不少(除了判据证不出的),补完从开始走得到交付。"""
    raw = _raw_graphs(monkeypatch)[template_id]
    stored = _stored_by_the_old_normalizer(raw)
    migrated = drawn_control_edges_come_back(stored)

    before, after = set(_control_wires(stored)), set(_control_wires(migrated))
    truth = set(_control_wires(raw))
    assert before < truth, "旧数据本来就该缺边(这条测试要能先红)"
    assert after <= truth, f"补出了作者没画过的控制边:{sorted(after - truth)}"
    still_missing = {(source, target) for source, target, _ in truth - after}
    assert still_missing <= _cases_the_rule_cannot_prove(stored), (
        f"作者画过的边还缺着,而且不是「判据证不出」的那种:{sorted(still_missing)}"
    )
    assert after - before, "一条都没补:这份旧数据不该什么都没发生"

    start, output = _start_and_output(migrated)
    assert output in _reachable_over_control(migrated, start), "补完还是沿控制边走不到交付"
    #: 数据边、活下来的控制边一条不动;补出来的边 id 不撞、不重、可重放。
    assert _data_wires(migrated) == _data_wires(stored)

    def control_rows(graph: dict[str, Any]) -> set[tuple[str, str, str, str]]:
        return {
            (str(edge.get("id")), str(edge.get("source")), str(edge.get("target")), str(edge.get("source_handle") or ""))
            for layer in _layers(graph)
            for edge in layer.get("edges") or []
            if edge.get("kind", "control") == "control"
        }

    assert control_rows(stored) <= control_rows(migrated), "活下来的控制边被改了 id / 来源 / 去向 / 走哪一支"
    restored_ids = [
        str(edge.get("id"))
        for layer in _layers(migrated)
        for edge in layer.get("edges") or []
        if edge.get("kind", "control") == "control" and str(edge.get("id")).startswith("c-")
    ]
    assert len(restored_ids) == len(set(restored_ids)) == len(after - before)
    #: 幂等:再跑一遍(连同升级链)什么都不变。
    assert drawn_control_edges_come_back(migrated) == migrated


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_证得出的旧图_迁移之后与作者画的一模一样(template_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """作者画的图里没有「判据证不出」的那种形状时,迁移结果与作者画的那张**逐条一致**(边、走哪一支)。

    这就是等价性证明:一张真实的作者图(victim = 原始图去掉那几条证不出的边)拿旧规范化折成旧数据,
    再跑迁移 —— 回到 victim 本身。**没有迁移时这条测试是红的**(下面第一句断言),不是碰巧相等。
    """
    raw = _raw_graphs(monkeypatch)[template_id]
    victim = _without_control_wires(raw, _cases_the_rule_cannot_prove(_stored_by_the_old_normalizer(raw)))
    stored = _stored_by_the_old_normalizer(victim)
    migrated = drawn_control_edges_come_back(stored)

    assert _control_wires(stored) != _control_wires(victim), "旧数据里作者的控制边就该是缺的(先红)"
    assert _control_wires(migrated) == _control_wires(victim)
    assert _data_wires(migrated) == _data_wires(stored)


def test_两种作者画法落库是同一个样子(monkeypatch: pytest.MonkeyPatch) -> None:
    """**为什么证不出来**:画了控制边被折掉 / 压根没画,旧数据里一模一样 —— 迁移只能选证得出的那一种。

    现场是 `product_pitch_presenter` 的 `hook_place`(作者画了 `pitch_project → hook_place`,
    同格上另有条件的真出口 `has_hook → hook_place`):把那条边从作者图里去掉,旧规范化交出的旧数据
    **逐字节相同**,迁移也只能补回其中一种 —— 这就是「一个旧数据对应两种作者画法」。
    """
    raw = _raw_graphs(monkeypatch)["product_pitch_presenter"]
    ambiguous = _cases_the_rule_cannot_prove(_stored_by_the_old_normalizer(raw))
    assert ("pitch_project", "hook_place") in ambiguous, "这条现场换形状了,换一对「目标另有路由控制边」的"
    never_drawn = _without_control_wires(raw, {("pitch_project", "hook_place")})
    assert _stored_by_the_old_normalizer(raw) == _stored_by_the_old_normalizer(never_drawn)
    assert _control_wires(drawn_control_edges_come_back(_stored_by_the_old_normalizer(raw))) == _control_wires(
        drawn_control_edges_come_back(_stored_by_the_old_normalizer(never_drawn))
    )


def test_新形状的图一条边都不动() -> None:
    """ADR 0063 之后存的图不是这个形状:作者画了控制边、或只是写了引用没画线 —— 都不许动。"""
    def graph(**edges: Any) -> dict[str, Any]:
        return {
            "nodes": [{"id": "a", "type": "template"}, {"id": "b", "type": "template"}],
            "edges": list(edges.values()),
        }

    data = {"id": "d-a-text-b-x", "source": "a", "target": "b", "kind": "data", "source_output": "text", "target_input": "x"}
    control = {"id": "e-a-b", "source": "a", "target": "b"}
    #: 画布上同一对节点连了数据线**和**控制线:那条控制线当年就折不掉,现在也不许动。
    assert drawn_control_edges_come_back(graph(data=data, control=control)) == graph(data=data, control=control)
    #: 目标是条件节点、旁边还有一条真出口:判据证不出,不补。
    conditional = {
        "nodes": [
            {"id": "a", "type": "template"},
            {"id": "c", "type": "condition"},
            {"id": "b", "type": "template"},
        ],
        "edges": [
            {"id": "d-a-text-b-x", "source": "a", "target": "b", "kind": "data", "source_output": "text", "target_input": "x"},
            {"id": "e-c-b", "source": "c", "target": "b", "source_handle": "true"},
        ],
    }
    assert drawn_control_edges_come_back(conditional) == conditional
    #: 目标另有一条普通控制入边、那条来源没有数据边:两组来源对不上,不补。
    sideways = {
        "nodes": [{"id": "a", "type": "template"}, {"id": "c", "type": "template"}, {"id": "b", "type": "template"}],
        "edges": [
            {"id": "d-a-text-b-x", "source": "a", "target": "b", "kind": "data", "source_output": "text", "target_input": "x"},
            {"id": "e-c-b", "source": "c", "target": "b"},
        ],
    }
    assert drawn_control_edges_come_back(sideways) == sideways


def test_新口径的官方模板_这条规则一条边都不动(monkeypatch: pytest.MonkeyPatch) -> None:
    """15 张模板按新口径规范化之后再过一遍(导入新导出、恢复新修订就走这条):图逐字节不变。

    这一条守的是「别把补线规则塞进生产路径之后,把新图也改了」:新图里"只是写了引用没画线"的 60 处一个都不许长线。
    """
    raw = _raw_graphs(monkeypatch)
    assert set(raw) == set(TEMPLATE_IDS)
    for template_id, graph in raw.items():
        normalized = normalize_graph(deepcopy(graph), node_types=NODE_TYPES)
        assert drawn_control_edges_come_back(normalized) == normalized, f"{template_id} 被改了"


def _legacy_graph(source: str | None) -> dict[str, Any]:
    """一张「旧数据」:作者画过 a→b 的控制边,规范化把它折了,只留下那条数据边。"""
    return {
        "meta": ({"source": "official", "template_id": "demo"} if source else {}),
        "nodes": [
            {"id": "a", "type": "template", "config": {"template": "写稿"}},
            {"id": "b", "type": "template", "config": {"template": ""}, "inputs": ["text"]},
        ],
        "edges": [{"id": "d-a-text-b-text", "source": "a", "target": "b", "kind": "data",
                   "source_output": "text", "target_input": "text"}],
    }


def _stored_graphs(ids: list[str]) -> dict[str, dict[str, Any]]:
    with engine.begin() as connection:
        return {
            workflow_id: json.loads(
                connection.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar_one()
            )
            for workflow_id in ids
        }


def _revision_count(workflow_id: str) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text("SELECT COUNT(*) FROM workflow_revisions WHERE workflow_id = :id"), {"id": workflow_id}
            ).scalar_one()
        )


def _put_legacy_graph(workflow_id: str, graph: dict[str, Any]) -> None:
    """把一张旧图放进库里 —— 当前图和它那一版修订都是旧样子(修订迁移之后的老库长这样)。"""
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE workflows SET graph = :graph, graph_hash = :digest WHERE id = :id"),
            {"graph": json.dumps(graph, ensure_ascii=False), "digest": graph_digest(graph), "id": workflow_id},
        )
        connection.execute(
            text("UPDATE workflow_revisions SET graph = :graph, graph_hash = :digest WHERE workflow_id = :id"),
            {"graph": json.dumps(graph, ensure_ascii=False), "digest": graph_digest(graph), "id": workflow_id},
        )






def test_恢复到升级之前的那一版_恢复的那份先升级_补回控制边() -> None:
    """修订快照是不可变的历史,**不重写它们**:回滚到旧修订时由恢复那条路(`upgrade_graph`)把边补回来。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/workflows", json={"workspace_id": workspace, "name": "流程"}).json()
    legacy = _legacy_graph(None)
    _put_legacy_graph(created["id"], legacy)
    with SessionLocal() as db:
        author = db.query(User).filter(User.username == "tester").one().id
        commit_graph_revision(db, db.get(Workflow, created["id"]), lambda _graph: {"nodes": [], "edges": []},
                              source="edit", created_by=author)
        db.commit()

    restored = client.post(f"/api/workflows/{created['id']}/revisions/1/restore")
    assert restored.status_code == 200, restored.text
    controls = [
        edge for edge in restored.json()["graph"]["edges"] if edge.get("kind", "control") == "control"
    ]
    assert controls == [{"id": "c-a-b", "source": "a", "target": "b"}]
    #: 快照本身还是那个样子(历史不许改):补的是恢复出来的那一版。
    with engine.begin() as connection:
        snapshot = json.loads(
            connection.execute(
                text("SELECT graph FROM workflow_revisions WHERE workflow_id = :id AND revision = 1"),
                {"id": created["id"]},
            ).scalar_one()
        )
    assert snapshot == legacy
