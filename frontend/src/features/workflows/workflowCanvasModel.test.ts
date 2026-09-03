import { describe, expect, it } from "vitest";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import {
  configAssetId,
  toWorkflowFlowEdges,
  toWorkflowFlowNodes,
  workflowIssueText,
} from "@/features/workflows/workflowCanvasModel";
import type { NodeIssue } from "@/features/workflows/analyze";

function meta(
  type: string,
  config: Record<string, unknown> = {},
  outputs: string[] = [],
): WorkflowNodeType {
  return {
    type,
    label: `${type} label`,
    description: "",
    category: "",
    config,
    outputs,
    output_types: {},
    plugin_name: "",
  };
}

const translate = ((key: MessageKey) => {
  if (key === "wfIssueRequired") return "缺少 {k}";
  if (key === "wfEdgeTrue") return "真";
  if (key === "wfEdgeFalse") return "假";
  return key;
}) as (key: MessageKey) => string;

describe("workflow canvas model", () => {
  it("projects runtime node metadata into the canvas node", () => {
    const registry = new Map([
      ["llm", meta("llm", {}, ["text", "*debug"])],
    ]);
    const graph: WorkflowGraph = {
      nodes: [{ id: "n1", type: "llm", name: "写标题", config: { model: "gpt-5" } }],
      edges: [],
    };

    const [node] = toWorkflowFlowNodes(graph, registry);

    expect(node.data).toMatchObject({
      label: "写标题",
      typeLabel: "llm label",
      outputs: ["text"],
      configSummary: "gpt-5",
    });
  });

  it("marks a data edge when declared source and target types conflict", () => {
    const registry = new Map([
      ["source", { ...meta("source", {}, ["text"]), output_types: { text: "text" } }],
      ["target", meta("target", { asset_id: { data_type: "asset" } })],
    ]);
    const graph: WorkflowGraph = {
      nodes: [{ id: "a", type: "source" }, { id: "b", type: "target", inputs: ["asset_id"] }],
      edges: [
        {
          id: "e1",
          source: "a",
          target: "b",
          kind: "data",
          source_output: "text",
          target_input: "asset_id",
        },
      ],
    };

    expect(toWorkflowFlowEdges(graph, translate, registry)[0].className).toContain("wf-edge-mismatch");
  });

  it("uses declared field labels in readiness messages", () => {
    const registry = new Map([
      ["custom", meta("custom", { source: { label: "输入素材", data_type: "asset" } })],
    ]);
    const issue: NodeIssue = {
      nodeId: "n1",
      nodeName: "自定义节点",
      nodeType: "custom",
      severity: "error",
      code: "required-missing",
      configKey: "source",
    };

    expect(workflowIssueText(translate, issue, registry)).toBe("缺少 输入素材");
  });

  it("finds a concrete configured asset by the declared input type", () => {
    const registry = new Map([
      ["custom", meta("custom", { source: { data_type: "asset" } })],
    ]);
    const node: WorkflowGraph["nodes"][number] = {
      id: "n1",
      type: "custom",
      config: { source: "asset-1" },
    };

    expect(configAssetId(node, registry)).toBe("asset-1");
    expect(configAssetId({ ...node, config: { source: "{{upstream.asset_id}}" } }, registry)).toBe("");
  });
});
