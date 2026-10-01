/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Edge, Node } from "@xyflow/react";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { toCanvas, toNodes } from "@/features/boards/boardCanvasModel";
import { useBoardHistory } from "@/features/boards/useBoardHistory";

/**
 * 性能棘轮(ADR 0025 Stage 4 的那一条的撤销这一侧):采用服务端的新一版**不碰撤销栈**。
 *
 * 此前每采用一次(每轮询到一次产出)就把撤销栈里的每一份快照 parse → 三方合并 → stringify 一遍:
 * 100 份 × 1000 格约一秒,主线程卡住,人一直在操作时每 2.5 秒卡一次。
 */

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function board(size: number): Canvas {
  const items: BoardItem[] = Array.from({ length: size }, (_, index) => ({
    id: `i${index}`,
    kind: index % 2 ? "image" : "note",
    x: index * 10,
    y: index,
    width: 260,
    height: 180,
    text: "x".repeat(200),
    form: { prompt: "p".repeat(300), parameters: { a: 1, b: "c" }, source_assets: [], producer: "generate" },
  }));
  return { items, edges: items.slice(1).map((item, index) => ({ id: `e${index}`, source: `i${index}`, target: item.id })), markers: [] };
}

it("撤销栈里 100 份、每份 1000 格:采用服务端的新一版不改写那一摞,一次采用在几十毫秒内", () => {
  const start = board(1000);
  const client = new QueryClient();
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(
    () => {
      const [nodes, setNodes] = React.useState<Node[]>(() => toNodes(start.items));
      const [edges, setEdges] = React.useState<Edge[]>(() => start.edges.map((edge) => ({ ...edge })));
      return { nodes, setNodes, ...useBoardHistory({ nodes, edges, setNodes, setEdges, onChange: () => undefined }) };
    },
    { wrapper },
  );
  for (let step = 1; step <= 100; step += 1) {
    act(() => result.current.setNodes((nodes) => nodes.map((node, index) => (index === 0 ? { ...node, position: { x: step, y: 0 } } : node))));
    act(() => void vi.advanceTimersByTime(400));
  }
  expect(result.current.history.past.length).toBe(100);
  const past = result.current.history.past;
  const current = toCanvas(result.current.nodes, []);
  const fresh: Canvas = { ...current, edges: start.edges, items: [...current.items, { id: "new", kind: "image", x: 0, y: 0, asset_id: "a1" }] };

  const began = performance.now();
  act(() => result.current.adopt(fresh));
  const took = performance.now() - began;

  expect(result.current.history.past, "撤销栈原样留着,一份都不重算").toBe(past);
  expect(took).toBeLessThan(250);
});
