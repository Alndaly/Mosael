/** @vitest-environment jsdom */
/**
 * 画布上的线**什么时候会动**:动画(`canvas-edge-live`)只挂在「运行走过」的线上。
 *
 * 「运行走过」= 这条边的两头都进了流程(不是 `skipped`):跑完的和正在跑的,都算 —— 节点一侧
 * 只有这两档状态,没有更细的「当前这根边」。此前动画长在所有数据线上,画布没在跑时也一片在动,
 * 被维护者读成「正在跑 / 有东西流过来」。现在没在跑的时候,一根线都不动。
 */
import { renderHook } from "@testing-library/react";
import { expect, it } from "vitest";

import type { Edge } from "@xyflow/react";

import { canvasEdgeClass } from "@/components/app/canvasEdges";
import type { Step } from "@/features/workflows/runSteps";
import { useWorkflowDisplayEdges } from "@/features/workflows/useWorkflowDisplayElements";
import type { WorkflowRunState } from "@/features/workflows/useWorkflowRun";

/** 一条数据线(静止的虚线)+ 一条普通控制线。 */
const edges: Edge[] = [
  { id: "d", source: "a", target: "b", className: canvasEdgeClass("data", { flow: true }), data: { kind: "data" } },
  { id: "c", source: "b", target: "c" },
];

const step = (nid: string, status: Step["status"]): Step => ({ nid, name: nid, status });

function shown(runByNode: WorkflowRunState["runByNode"]) {
  return renderHook(() => useWorkflowDisplayEdges(edges, runByNode, "default")).result.current;
}

it("没在跑:一根线都不动 —— 数据线还是那条静止的虚线", () => {
  const shownEdges = shown({});
  expect(shownEdges[0].className).toBe(canvasEdgeClass("data", { flow: true }));
  expect(shownEdges[0].className).not.toContain("canvas-edge-live");
  expect(shownEdges[1].className).toBeUndefined();
});

it("跑过 / 正在跑:那条边换成「运行走过」—— 虚线,而且在走", () => {
  //: 「正在跑」的那一步(b)和跑完的(a)都算走过:started 事件一到,这一步的状态就是 running。
  const shownEdges = shown({ a: step("a", "done"), b: step("b", "running") });
  expect(shownEdges[0].className).toBe(canvasEdgeClass("taken"));
  expect(shownEdges[0].className).toContain("canvas-edge-live");
  expect(shownEdges[0].className).toContain("canvas-edge-flow");
});

it("有一头没进流程(skipped):这根没走过,不动", () => {
  const shownEdges = shown({ a: step("a", "done"), c: step("c", "skipped") });
  expect(shownEdges.map((edge) => edge.className)).toEqual([canvasEdgeClass("data", { flow: true }), undefined]);
});
