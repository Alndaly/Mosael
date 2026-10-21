/** @vitest-environment jsdom */
/**
 * 画布节点的逐帧身份稳定:输入没变,节点对象原样复用(React Flow 才跳过重渲染);
 * 只有被拖的节点换对象 —— 这是拖拽流畅度的关键(见 useWorkflowDisplayElements 的缓存注释)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import type { Node } from "@xyflow/react";

import type { WorkflowGraph } from "@/api/client";
import { useWorkflowDisplayNodes } from "@/features/workflows/useWorkflowDisplayElements";

const graph: WorkflowGraph = {
  nodes: [
    { id: "a", type: "llm", position: { x: 0, y: 0 }, config: {} },
    { id: "b", type: "template", position: { x: 200, y: 0 }, config: {} },
  ],
  edges: [],
};

// data 对象也按节点稳定(真实路径里 applyNodeChanges 保 data 身份,只有被拖节点换新对象)。
const dataOf = new Map(graph.nodes.map((one) => [one.id, { nodeType: one.type }]));
const rfNodes = (): Node[] =>
  graph.nodes.map((one) => ({
    id: one.id,
    type: "wf",
    position: one.position ?? { x: 0, y: 0 },
    data: dataOf.get(one.id)!,
  }));

// 稳定字面量(引用级):每次渲染新建会打碎缓存的签名,那就测不到「输入没变」的本意了。
const STABLE = {
  registry: new Map(),
  t: (key: string) => key,
  layerIssues: new Map(),
  runByNode: {},
  nodeZ: {},
  markers: [] as never[],
  patchMarker: () => {},
  deleteMarker: () => {},
  refName: () => "",
  portNamer: {} as never,
};

function shown() {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
  );
  return renderHook(
    ({ nodes }: { nodes: Node[] }) =>
      useWorkflowDisplayNodes({
        nodes,
        graph,
        workspaceId: "w",
        markerMode: false,
        markersVisible: false,
        annotationMode: false,
        searchHit: null,
        atRoot: true,
        ...STABLE,
      }),
    { wrapper, initialProps: { nodes: rfNodes() } },
  );
}

describe("画布节点的身份稳定", () => {
  it("输入没变(重渲染):每个节点对象原样复用,一帧都不重画", () => {
    const hook = shown();
    const first = hook.result.current;
    const sameNodes = rfNodes();
    hook.rerender({ nodes: sameNodes });
    const again = hook.result.current;
    expect(again[0]).toBe(first[0]);
    expect(again[1]).toBe(first[1]);
  });

  it("只有一颗的位置变了:只有那颗是新对象,另一颗身份不变", () => {
    const hook = shown();
    const first = hook.result.current;
    // 模拟 applyNodeChanges:被拖节点换新对象,但 data 身份保住
    const moved = rfNodes();
    moved[1] = { ...moved[1], position: { x: 300, y: 40 }, dragging: true };
    hook.rerender({ nodes: moved });
    const after = hook.result.current;
    expect(after[0]).toBe(first[0]);
    expect(after[1]).not.toBe(first[1]);
    expect(after[1].position).toEqual({ x: 300, y: 40 });
  });
});
