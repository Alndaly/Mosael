"""「引用了一个节点没有的输出」的后端一侧:跑 contracts/workflow-output-reference-cases.json。

画布那一侧(analyze.ts 的 outputReferenceProblems)跑同一份语料,见 outputReferences.parity.test.ts。两侧不一致的样子:
画布全绿、点了运行被拒;或者画布标红、后端照跑 —— 正是这份契约要防的。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.workflows import NODE_TYPES
from app.domain.workflows.graph_rules import output_reference_problems

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

CORPUS = json.loads((Path(__file__).resolve().parents[2] / "contracts/workflow-output-reference-cases.json").read_text())
CASES = CORPUS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_output_reference_contract(case: dict) -> None:
    assert output_reference_problems(case["graph"], CORPUS["node_types"]) == case["problems"]


@pytest.mark.parametrize("node_type", sorted(name for name in CORPUS["node_types"] if not name.startswith("plugin.")))
def test_语料里写的节点声明和真目录对得上(node_type: str) -> None:
    """两侧都照着语料里的 `node_types` 判;它和真目录对不上,语料钉住的就不是真在跑的那份规矩。"""
    declared = CORPUS["node_types"][node_type]
    real = NODE_TYPES[node_type]
    assert declared["outputs"] == real["outputs"]
    assert declared.get("output_schema_from") == real.get("output_schema_from")
    assert declared.get("body_scope") == real.get("body_scope")
    assert {key: spec["type"] for key, spec in declared["config"].items()} == {
        key: real["config"][key]["type"] for key in declared["config"]
    }


def test_用例里的每种节点都在语料的声明里_没装的插件除外() -> None:
    def types(graph: dict) -> set[str]:
        found = set()
        for node in graph["nodes"]:
            found.add(node["type"])
            body = node.get("config", {}).get("body")
            if isinstance(body, dict):
                found |= types(body)
        return found

    used = set().union(*(types(case["graph"]) for case in CASES))
    assert used - set(CORPUS["node_types"]) == {"plugin.removed.tool"}, "只有那个故意没装的插件不在声明里"
