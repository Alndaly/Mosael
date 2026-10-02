import { describe, expect, it } from "vitest";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import {
  configAssetId,
  toWorkflowFlowEdges,
  toWorkflowFlowNodes,
  withSingleNodeSelected,
  workflowPortPresentation,
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
    output_labels: {},
    plugin_name: "",
    tool_name: "",
  };
}

const translate = ((key: MessageKey) => {
  if (key === "wfIssueRequired") return "缺少 {k}";
  if (key === "wfEdgeTrue") return "真";
  if (key === "wfEdgeFalse") return "假";
  return key;
}) as (key: MessageKey) => string;

describe("workflow canvas model", () => {
  it("keeps the visual node selection aligned with the inspector target", () => {
    const nodes = [
      { id: "source", position: { x: 0, y: 0 }, data: {}, selected: true },
      { id: "project", position: { x: 100, y: 0 }, data: {}, selected: false },
    ];

    expect(withSingleNodeSelected(nodes, "project").map((node) => [node.id, node.selected])).toEqual([
      ["source", false],
      ["project", true],
    ]);
    expect(withSingleNodeSelected(nodes, null).every((node) => node.selected === false)).toBe(true);
  });

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

  it("开始节点有几个参数就有几个输出口;从参数拉出的数据边落在那个参数的口上", () => {
    //: 开始节点声明的是 `*params`(「params 里的每个键」)。此前通配一律滤掉,卡片上只有顶上那一个控制出口,
    //: 引用 `{{start.x}}` 的线、从参数拉出的数据边全都挤在它上面。
    const registry = new Map([
      ["start", meta("start", { params: { type: "object" } }, ["*params"])],
      ["llm", meta("llm", { prompt: { type: "template" } }, ["text"])],
    ]);
    const graph: WorkflowGraph = {
      nodes: [
        { id: "start", type: "start", config: { params: { account_link: "", post_count: 30 } } },
        { id: "n1", type: "llm", inputs: ["prompt"], config: { prompt: "" } },
      ],
      edges: [{ id: "d1", source: "start", target: "n1", kind: "data", source_output: "post_count", target_input: "prompt" }],
    };

    const [start] = toWorkflowFlowNodes(graph, registry);
    expect(start.data).toMatchObject({ outputs: ["account_link", "post_count"] });
    expect(toWorkflowFlowEdges(graph, translate, registry)[0]).toMatchObject({ sourceHandle: "out:post_count", targetHandle: "in:prompt" });
    //: 没有参数的开始节点照旧没有输出口(只有控制出口)。
    expect(toWorkflowFlowNodes({ nodes: [{ id: "start", type: "start", config: {} }], edges: [] }, registry)[0].data).toMatchObject({ outputs: [] });
  });

  it("每条数据边两头的口都画出来:连接态没记上的输入、注册表里没有的输出(插件没装)", () => {
    //: 口不在,React Flow 就不画这根线(只报 008),人看不见它,也就删不掉。
    const registry = new Map([["llm", meta("llm", { prompt: { type: "template" } }, ["text"])]]);
    const graph: WorkflowGraph = {
      nodes: [
        { id: "tool", type: "plugin.gone.tool", config: {} },
        { id: "n1", type: "llm", config: { prompt: "" } },
      ],
      edges: [{ id: "d1", source: "tool", target: "n1", kind: "data", source_output: "result", target_input: "prompt" }],
    };
    const [tool, llm] = toWorkflowFlowNodes(graph, registry);
    expect(tool.data).toMatchObject({ outputs: ["result"] });
    expect(llm.data).toMatchObject({ inputs: ["prompt"], outputs: ["text"] });
  });

  it("条件节点:接了上游的输入照画;出口是标题层的真 / 假两路,result 只有数据边拉出时才画口", () => {
    const registry = new Map([["condition", meta("condition", { left: { type: "template" } }, ["result"])]]);
    const gate = { id: "c", type: "condition", inputs: ["left"], config: { left: "" } };
    expect(toWorkflowFlowNodes({ nodes: [gate], edges: [] }, registry)[0].data).toMatchObject({ inputs: ["left"], outputs: [] });
    const wired: WorkflowGraph = {
      nodes: [gate, { id: "n", type: "condition", config: {} }],
      edges: [{ id: "d", source: "c", target: "n", kind: "data", source_output: "result", target_input: "left" }],
    };
    expect(toWorkflowFlowNodes(wired, registry).map((node) => node.data)).toMatchObject([
      { inputs: ["left"], outputs: ["result"] },
      { inputs: ["left"], outputs: [] },
    ]);
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

    expect(toWorkflowFlowEdges(graph, translate, registry)[0].className).toContain("canvas-edge-mismatch");
  });

  it("uses declared field labels in readiness messages", () => {
    const registry = new Map([
      ["custom", meta("custom", { source: { label: "输入素材", data_type: "asset" } })],
    ]);
    const issue: NodeIssue = {
      nodeId: "n1",
      path: [],
      nodeName: "自定义节点",
      nodeType: "custom",
      severity: "error",
      code: "required-missing",
      configKey: "source",
    };

    expect(workflowIssueText(translate, issue, registry)).toBe("缺少 输入素材");
  });

  it("插件节点用不了:有后端给的原因就说原因,还没问到才退回笼统的那句", () => {
    const issue: NodeIssue = {
      nodeId: "p1", path: [], nodeName: "放大", nodeType: "plugin.comfy.upscale", severity: "error", code: "unknown-type",
    };
    const say = ((key: MessageKey) => (key === "wfIssuePluginUnusable" ? "不可用:{reason}" : key)) as (key: MessageKey) => string;
    const reasons = new Map([["plugin.comfy.upscale", "你还没有接「ComfyUI」"]]);
    expect(workflowIssueText(say, issue, new Map(), reasons)).toBe("不可用:你还没有接「ComfyUI」");
    expect(workflowIssueText(say, issue, new Map())).toBe("wfIssuePluginUnavailable");
  });

  it("被引用着却不会跑:点名谁引用了它、怎么引用的", () => {
    const issue: NodeIssue = {
      nodeId: "props", path: [], nodeName: "可用的 3D 道具", nodeType: "scene_props", severity: "error",
      code: "unwired-referenced", referencedBy: ["布景", "分镜"], refs: ["{{props.catalog}}", "{{props.names}}"],
    };
    const say = ((key: MessageKey) =>
      key === "wfIssueUnwiredReferenced" ? "「{names}」引用了它({refs})" : key === "listSeparator" ? "、" : key) as (key: MessageKey) => string;
    expect(workflowIssueText(say, issue, new Map())).toBe("「布景、分镜」引用了它({{props.catalog}}、{{props.names}})");
  });

  it("keeps stable port keys while projecting localized labels for both sides", () => {
    const registry = new Map([
      [
        "timeline",
        {
          ...meta("timeline", { sequence_id: { label: "时间线", data_type: "sequence" } }, ["sequence_id", "revision"]),
          output_types: { sequence_id: "sequence", revision: "number" },
          output_labels: { sequence_id: "时间线", revision: "版本" },
        },
      ],
    ]);

    expect(
      workflowPortPresentation(
        { nodeType: "timeline", inputs: ["sequence_id"], outputs: ["sequence_id", "revision"] },
        registry,
      ),
    ).toEqual({
      inputTypes: { sequence_id: "sequence" },
      inputLabels: { sequence_id: "时间线" },
      outputTypes: { sequence_id: "sequence", revision: "number" },
      outputLabels: { sequence_id: "时间线", revision: "版本" },
    });
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


describe("标记", () => {
  it("和节点一起画在画布上,但 id 带前缀、类型不是 wf", () => {
    const graph = {
      nodes: [{ id: "start", type: "start", position: { x: 0, y: 0 } }],
      edges: [],
      markers: [{ id: "m1", name: "这一段", x: 640, y: 120, shortcut: "Mod+Alt+2" }],
    } as unknown as WorkflowGraph;

    const nodes = toWorkflowFlowNodes(graph, new Map());
    const marker = nodes.find((node) => node.type === "marker");
    // 前缀是必须的:图里 markers 和 nodes 是两份列表,一个和节点重名的标记会把它顶掉。
    expect(marker?.id).toBe("marker:m1");
    expect(marker?.position).toEqual({ x: 640, y: 120 });
    expect(nodes.filter((node) => node.type === "wf").map((node) => node.id)).toEqual(["start"]);
  });

  it("没有标记的图照旧只有节点", () => {
    const graph = { nodes: [{ id: "start", type: "start" }], edges: [] } as unknown as WorkflowGraph;
    expect(toWorkflowFlowNodes(graph, new Map()).every((node) => node.type === "wf")).toBe(true);
  });
});
