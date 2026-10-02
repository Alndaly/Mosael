"""「一定不会跑」与「会跑的节点引用了它」的后端一侧:跑 contracts/workflow-never-run-cases.json。

画布那一侧(analyze.ts 的 neverRunNodes / neverRunReferences)跑同一份语料,见 neverRuns.parity.test.ts。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.workflows import NODE_TYPES, never_run_nodes, never_run_references

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

CORPUS = json.loads((Path(__file__).resolve().parents[2] / "contracts/workflow-never-run-cases.json").read_text())
CASES = CORPUS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_never_run_contract(case: dict) -> None:
    entry_is_root = case["entry_is_root"]
    assert sorted(never_run_nodes(case["graph"], entry_is_root=entry_is_root)) == case["never_runs"]
    assert never_run_references(case["graph"], entry_is_root=entry_is_root) == case["blocked"]


@pytest.mark.parametrize("node_type", sorted(CORPUS["node_types"]))
def test_语料里写的节点声明和真目录对得上(node_type: str) -> None:
    """画布那一侧照着语料里的 `node_types` 认代码字段、体字段;它和真目录对不上,两侧就是在各跑各的图。"""
    declared = CORPUS["node_types"][node_type]
    real = NODE_TYPES[node_type]
    assert {key: spec["type"] for key, spec in declared["config"].items()} == {
        key: real["config"][key]["type"] for key in declared["config"]
    }
    assert declared.get("body_scope") == real.get("body_scope")


def test_用例里的每种节点都在语料的声明里() -> None:
    def types(graph: dict) -> set[str]:
        found = set()
        for node in graph["nodes"]:
            found.add(node["type"])
            body = node.get("config", {}).get("body")
            if isinstance(body, dict):
                found |= types(body)
        return found

    used = set().union(*(types(case["graph"]) for case in CASES))
    assert used <= set(CORPUS["node_types"]), used - set(CORPUS["node_types"])
