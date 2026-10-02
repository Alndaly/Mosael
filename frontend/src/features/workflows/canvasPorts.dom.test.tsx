/** @vitest-environment jsdom */
/**
 * **连线指向的口,卡片上一定画着。**
 *
 * React Flow 找不到一条线指向的口时不画这根线,只在控制台报一句 008 —— 画布上看不出少了什么。此前条件节点为了
 * 紧凑不画数据接点,于是「认出的平台 → 是抖音吗」这类数据边(`link.platform` → `tk_is_dy` 的 `in:left`)在官方模板里
 * 一根都没画出来,控制台被 008 刷屏。
 *
 * 节点目录在后端;这里读后端导出的接点快照(api/generated/workflow-node-ports.json,由 backend/scripts/export_openapi.py
 * 生成,后端测试守它的新鲜度),而不是另抄一份。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import PORTS from "@/api/generated/workflow-node-ports.json";
import { canTakeUpstream } from "@/features/nodeForms/fieldTypes";
import { WORKFLOW_NODE_TYPES } from "@/features/workflows/WorkflowNode";
import { declaredFieldNames } from "@/features/workflows/scope";
import { toWorkflowFlowNodes } from "@/features/workflows/workflowCanvasModel";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

type Ports = { type: string; config: Record<string, { type?: string; editor?: string }>; outputs: string[] };

const REGISTRY = new Map<string, WorkflowNodeType>(
  (PORTS as unknown as Ports[]).map((one) => [
    one.type,
    { ...one, label: one.type, description: "", category: "", plugin_name: "", tool_name: "" } as WorkflowNodeType,
  ]),
);

/** 把一层图画到画布上,交回每个节点卡片上画着的口(节点 id → handle id)。 */
function drawnPorts(graph: WorkflowGraph): Map<string, Set<string>> {
  const { container, unmount } = render(
    <QueryClientProvider client={new QueryClient()}>
      <ReactFlowProvider>
        <div style={{ width: 1200, height: 800 }}>
          <ReactFlow nodes={toWorkflowFlowNodes(graph, REGISTRY)} edges={[]} nodeTypes={WORKFLOW_NODE_TYPES} />
        </div>
      </ReactFlowProvider>
    </QueryClientProvider>,
  );
  const ports = new Map<string, Set<string>>();
  for (const node of container.querySelectorAll<HTMLElement>(".react-flow__node")) {
    const ids = [...node.querySelectorAll<HTMLElement>(".react-flow__handle")].map((handle) => handle.dataset.handleid ?? "");
    ports.set(node.dataset.id ?? "", new Set(ids));
  }
  unmount();
  return ports;
}

describe("每种节点", () => {
  //: 开始节点是入口,前面什么都没有,不接上游(检查器里也不给开关)。
  const types = [...REGISTRY.values()];

  it("快照里有节点", () => {
    expect(types.length).toBeGreaterThan(40);
    expect(REGISTRY.get("condition")?.config).toHaveProperty("left");
  });

  it("能接上游的字段接上之后,卡片上都有那个输入口;声明的每个输出都有输出口(条件节点的出口是真 / 假两路)", () => {
    const nodes = types.map((meta, index) => {
      const config = meta.type === "start" ? { params: { topic: "", style: "" } } : {};
      const inputs =
        meta.type === "start"
          ? []
          : Object.entries(meta.config as Record<string, { type?: string }>).filter(([, spec]) => canTakeUpstream(spec)).map(([key]) => key);
      return { id: `n${index}`, type: meta.type, position: { x: 0, y: index * 300 }, inputs, config };
    });
    const ports = drawnPorts({ nodes, edges: [] });
    const missing = nodes.flatMap((node) => {
      const meta = REGISTRY.get(node.type)!;
      const want = [
        ...node.inputs.map((key) => `in:${key}`),
        ...(node.type === "condition" ? ["true", "false"] : declaredFieldNames(meta.outputs, node.config).map((name) => `out:${name}`)),
      ];
      return want.filter((id) => !ports.get(node.id)?.has(id)).map((id) => `${node.type} ${id}`);
    });
    expect(missing).toEqual([]);
  });
});

const DIR = join(import.meta.dirname, "../../../../website/public/workflows");
const COPIES = readdirSync(DIR).filter((name) => name.endsWith(".zh.mosael-workflow.json")).sort();

/** 一张图和它里面的每一层体(循环 / 子图)。 */
function layers(graph: WorkflowGraph, path: string[] = []): Array<{ path: string; graph: WorkflowGraph }> {
  return [
    { path: path.join(" / ") || "主流程", graph },
    ...graph.nodes.flatMap((node) =>
      Object.values(node.config ?? {})
        .filter((value): value is WorkflowGraph => Boolean(value && typeof value === "object" && Array.isArray((value as WorkflowGraph).nodes)))
        .flatMap((body) => layers(body, [...path, node.id])),
    ),
  ];
}

describe("官方模板", () => {
  it("一份都没漏读", () => {
    expect(COPIES.length).toBeGreaterThan(5);
  });

  it.each(COPIES)("%s:每条连线两头的口卡片上都画着", (name) => {
    const graph = (JSON.parse(readFileSync(join(DIR, name), "utf8")) as { graph: WorkflowGraph }).graph;
    const broken: string[] = [];
    for (const layer of layers(graph)) {
      const unknown = layer.graph.nodes.filter((node) => !REGISTRY.has(node.type)).map((node) => node.type);
      expect(unknown, `${layer.path} 里有快照里没有的节点类型`).toEqual([]);
      const ports = drawnPorts(layer.graph);
      for (const edge of layer.graph.edges) {
        const source = edge.kind === "data" ? `out:${edge.source_output}` : edge.source_handle;
        const target = edge.kind === "data" ? `in:${edge.target_input}` : null;
        if (source && !ports.get(edge.source)?.has(source)) broken.push(`${layer.path}:${edge.id} 的 ${edge.source} 没有 ${source}`);
        if (target && !ports.get(edge.target)?.has(target)) broken.push(`${layer.path}:${edge.id} 的 ${edge.target} 没有 ${target}`);
      }
    }
    expect(broken).toEqual([]);
  });
});
