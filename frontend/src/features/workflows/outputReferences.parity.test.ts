/**
 * 「引用了一个节点没有的输出」的画布一侧:跑 contracts/workflow-output-reference-cases.json。
 *
 * 后端运行前按 graph_rules.output_reference_problems 拦(backend/tests/test_workflow_output_reference_parity.py 跑同一份语料);
 * 画布据同一个判据在引用方身上标 error(output-missing / field-missing)、运行键跟着灰掉。两侧不一致的样子:画布全绿、
 * 点了运行被拒;或者画布标红、后端照跑 —— 正是这份契约要防的。
 *
 * 语料里的 `node_types` 是两侧判输出要用的那几格(outputs、output_schema_from、代码字段、体字段;后端那条测试核对它和真目录对得上)。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-output-reference-cases.json";

import type { WorkflowGraph } from "@/api/client";
import { analyzeWorkflow, outputReferenceProblems, type AnalyzeContext, type RegistryLike } from "@/features/workflows/analyze";

const registry: RegistryLike = {
  get: (type) => (contract.node_types as Record<string, ReturnType<RegistryLike["get"]>>)[type],
};

describe("引用了一个节点没有的输出(契约)", () => {
  it.each(contract.cases)("$name", ({ graph, problems }) => {
    expect(outputReferenceProblems(graph as unknown as WorkflowGraph, registry)).toEqual(problems);
  });
});

describe("就绪清单里的样子", () => {
  const ctx: AnalyzeContext = {
    chatProfileIds: new Set(),
    chatProfilesLoaded: true,
    generationVendors: new Set(),
    generationModelsLoaded: true,
  };

  it("指不到的输出挂在引用方身上、是 error(运行键灰掉),说清被引用的是谁、它有哪些", () => {
    const graph = contract.cases[0].graph as unknown as WorkflowGraph;
    const analysis = analyzeWorkflow(graph, registry, ctx);
    const missing = analysis.issues.filter((issue) => issue.code === "output-missing");
    expect(missing).toEqual([
      expect.objectContaining({ nodeId: "u", severity: "error", ref: "{{t.nokey}}", sourceName: "template(t)", available: ["text"], configKey: "template" }),
    ]);
    expect(analysis.runnable).toBe(false);
  });
});
