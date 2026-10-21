/** @vitest-environment jsdom */
/**
 * 拖拽期间位置不写回 graph(就绪分析/引用线/道次排序整条派生链每帧重算,拖起来掉帧);
 * dragStop 一次性落最终位置;键盘挪动的 position(没有 drag 生命周期)照旧即时落。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { useWorkflowCanvasEdits } from "@/features/workflows/useWorkflowCanvasEdits";

function setup(graph: WorkflowGraph) {
  const setGraph = vi.fn((updater: unknown, _opts?: unknown) => {
    if (typeof updater === "function") updater(graph);
  });
  const setDirty = vi.fn();
  const setNodes = vi.fn();
  const setEdges = vi.fn();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () =>
      useWorkflowCanvasEdits({
      graph,
      setGraph,
      applyGraph: vi.fn(),
      registry: new Map(),
      t: (key: string) => key,
      nodes: [],
      setNodes,
      setEdges,
      setDirty,
      canAddStart: false,
      selectedFlowIds: new Set(),
      selectInspectorNode: vi.fn(),
      focusPosition: vi.fn(),
      rfRef: React.createRef(),
      canvasSurfaceRef: React.createRef(),
      getCanvasInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
        workspaceId: "w1",
      }),
    { wrapper },
  );
  return { result, setGraph, setDirty };
}

const position = (id: string, x: number) => ({ type: "position" as const, id, position: { x, y: 0 }, dragging: true });

describe("拖拽期间位置延迟落 graph", () => {
  it("dragStart 后连发 position:dragStop 前一次 graph 都不写,dragStop 落一次且是最终位置", () => {
    const graph: WorkflowGraph = { nodes: [{ id: "n1", type: "llm", position: { x: 0, y: 0 }, config: {} }], edges: [] };
    const { result, setGraph, setDirty } = setup(graph);

    act(() => result.current.handleNodeDragStart());
    act(() => result.current.onNodesChange([position("n1", 10)]));
    act(() => result.current.onNodesChange([position("n1", 20)]));
    act(() => result.current.onNodesChange([position("n1", 30)]));
    // 拖拽中:视觉那份(nodes 状态)每帧照走,graph 一下都不碰
    expect(setGraph).not.toHaveBeenCalled();

    act(() => result.current.handleNodeDragStop());
    expect(setGraph).toHaveBeenCalledTimes(1);
    expect(setDirty).toHaveBeenCalledWith(true);
    const updater = setGraph.mock.calls[0][0];
    const next = (updater as (g: WorkflowGraph) => WorkflowGraph)(graph);
    expect(next.nodes.find((n) => n.id === "n1")?.position).toEqual({ x: 30, y: 0 });
  });

  it("没有 drag 生命周期的 position(键盘方向键)照旧即时写 graph", () => {
    const graph: WorkflowGraph = { nodes: [{ id: "n1", type: "llm", position: { x: 0, y: 0 }, config: {} }], edges: [] };
    const { result, setGraph } = setup(graph);

    act(() => result.current.onNodesChange([position("n1", 8)]));
    expect(setGraph).toHaveBeenCalledTimes(1);
    const next = (setGraph.mock.calls[0][0] as (g: WorkflowGraph) => WorkflowGraph)(graph);
    expect(next.nodes.find((n) => n.id === "n1")?.position).toEqual({ x: 8, y: 0 });
  });

  it("dragStart 后原样放下(没动):dragStop 不写 graph 也不弄脏", () => {
    const graph: WorkflowGraph = { nodes: [{ id: "n1", type: "llm", position: { x: 0, y: 0 }, config: {} }], edges: [] };
    const { result, setGraph, setDirty } = setup(graph);

    act(() => result.current.handleNodeDragStart());
    act(() => result.current.handleNodeDragStop());
    expect(setGraph).not.toHaveBeenCalled();
    expect(setDirty).not.toHaveBeenCalled();
  });
});
