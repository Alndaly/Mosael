/** @vitest-environment jsdom */
/**
 * 引用提示线画到 DOM 上是什么样:真的交给 React Flow 渲染一遍。
 *
 * jsdom 里节点量不出尺寸、接点量不出位置,所以节点按 React Flow 的服务端渲染写法直接给出宽高和接点(`width` /
 * `height` / `handles`)—— 线因此画得出来。断言看的是 React Flow 交出来的真实 DOM:挂的是哪种样子、能不能选中、
 * 能不能拖去重连、有没有箭头、悬停说明在不在。线色线宽本身由 canvasEdges 的测试和编出来的样式(compiledCascade)核对。
 */
import { act, fireEvent, render } from "@testing-library/react";
import { Position, ReactFlow, ReactFlowProvider, type Node } from "@xyflow/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { CANVAS_EDGE_OPTIONS } from "@/components/app/canvasEdges";
import { WORKFLOW_CANVAS_EDGE_TYPES } from "@/features/workflows/ReferenceHintEdge";
import { toReferenceHintEdges } from "@/features/workflows/referenceHints";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

function box(id: string, x: number): Node {
  return {
    id,
    position: { x, y: 0 },
    data: { label: id },
    width: 160,
    height: 60,
    handles: [
      { type: "target", position: Position.Left, x: 0, y: 25, width: 9, height: 9 },
      { type: "source", position: Position.Right, x: 151, y: 25, width: 9, height: 9 },
      { id: "out:text", type: "source", position: Position.Right, x: 151, y: 45, width: 9, height: 9 },
    ],
  };
}

const say = (key: string) =>
  ({ wfRefHint: "引用 {refs}(只管先后,不会让「{source}」运行)", wfRefHintNeverRuns: "「{source}」不会跑:{refs}", listSeparator: "、" })[key] ?? key;

const edges = toReferenceHintEdges(
  [
    { id: "ref-hint:plan>out:text>shot", source: "plan", sourceHandle: "out:text", target: "shot", refs: ["{{plan.text}}"], neverRuns: false },
    { id: "ref-hint:props>>shot", source: "props", sourceHandle: null, target: "shot", refs: ["{{props.catalog}}"], neverRuns: true },
  ],
  { shape: "default", t: say as never, nodeName: (id) => id },
);

function renderFlow(onEdgesChange = vi.fn()) {
  const view = render(
    <ReactFlowProvider>
      <div style={{ width: 800, height: 400 }}>
        <ReactFlow
          nodes={[box("plan", 0), box("props", 0), box("shot", 400)]}
          edges={edges}
          edgeTypes={WORKFLOW_CANVAS_EDGE_TYPES}
          defaultEdgeOptions={CANVAS_EDGE_OPTIONS}
          onEdgesChange={onEdgesChange}
        />
      </div>
    </ReactFlowProvider>,
  );
  const edge = (id: string) => view.container.querySelector<SVGGElement>(`.react-flow__edge[data-id="${id}"]`);
  return { view, edge, onEdgesChange };
}

describe("引用提示线画在画布上", () => {
  it("挂的是提示线那一种样子;错误态是另一种颜色", () => {
    const { edge } = renderFlow();
    const ok = edge("ref-hint:plan>out:text>shot");
    const broken = edge("ref-hint:props>>shot");
    expect(ok).not.toBeNull();
    expect(broken).not.toBeNull();
    expect(ok!.classList).toContain("canvas-edge-ref");
    expect(ok!.classList).toContain("canvas-edge-hint");
    expect(broken!.classList).toContain("canvas-edge-ref-never-runs");
    expect(broken!.classList).toContain("canvas-edge-hint");
  });

  it("不可选、不进 Tab 序、没有重连的把手;不画箭头", () => {
    const { edge } = renderFlow();
    for (const id of ["ref-hint:plan>out:text>shot", "ref-hint:props>>shot"]) {
      const g = edge(id)!;
      expect(g.classList).not.toContain("selectable");
      //: xyflow 给它挂 inactive(pointer-events: none);canvas-edge-hint 把悬停还回来(见 canvasEdges)。
      expect(g.classList).toContain("inactive");
      expect(g.getAttribute("tabindex")).toBeNull();
      expect(g.querySelector(".react-flow__edgeupdater")).toBeNull();
      expect(g.querySelector(".react-flow__edge-path")!.getAttribute("marker-end")).toBeNull();
    }
  });

  it("悬停说明:线上挂着 <title>,也是它的无障碍名字", () => {
    const { edge } = renderFlow();
    const g = edge("ref-hint:plan>out:text>shot")!;
    expect(g.querySelector("title")?.textContent).toBe("引用 {{plan.text}}(只管先后,不会让「plan」运行)");
    expect(g.getAttribute("aria-label")).toBe("引用 {{plan.text}}(只管先后,不会让「plan」运行)");
    expect(edge("ref-hint:props>>shot")!.querySelector("title")?.textContent).toBe("「props」不会跑:{{props.catalog}}");
  });

  it("点它不会选中它(也就删不掉)", async () => {
    const { edge, onEdgesChange } = renderFlow();
    await act(async () => {
      fireEvent.click(edge("ref-hint:plan>out:text>shot")!);
    });
    expect(onEdgesChange.mock.calls.flat(2).filter((change: { type?: string }) => change.type === "select")).toEqual([]);
    expect(edge("ref-hint:plan>out:text>shot")!.classList).not.toContain("selected");
  });
});
