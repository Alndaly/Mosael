/**
 * 「一定不会跑」与「会跑的节点引用了它」的画布一侧:跑 contracts/workflow-never-run-cases.json。
 *
 * 后端运行前按 graph_rules.never_run_references 拦(backend/tests/test_workflow_never_run_parity.py 跑同一份语料);
 * 画布据同一个判据把被引用的节点标成 error、把引用画成错误色的虚线。两侧不一致的样子:画布全绿、点了运行被拒;
 * 或者画布标红、后端照跑 —— 正是这份契约要防的。
 *
 * 语料里的 `node_types` 是画布认代码字段、体字段要用的那几格(后端那条测试核对它和真目录对得上)。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-never-run-cases.json";

import type { WorkflowGraph } from "@/api/client";
import { neverRunNodes, neverRunReferences, type RegistryLike } from "@/features/workflows/analyze";

const registry: RegistryLike = {
  get: (type) => (contract.node_types as Record<string, ReturnType<RegistryLike["get"]>>)[type],
};

describe("一定不会跑的节点(契约)", () => {
  it.each(contract.cases)("$name", ({ graph, entry_is_root, never_runs, blocked }) => {
    const layer = graph as unknown as WorkflowGraph;
    expect([...neverRunNodes(layer, { entryIsRoot: entry_is_root })].sort()).toEqual(never_runs);
    expect(neverRunReferences(layer, registry, { entryIsRoot: entry_is_root })).toEqual(
      blocked.map((one) => ({ source: one.source, referencedBy: one.referenced_by, refs: one.refs })),
    );
  });
});
