/** @vitest-environment jsdom */
/**
 * 同一对节点之间的多条边**画出来不叠在一起** —— 真的交给 React Flow 渲染一遍,看它交出来的 `d`。
 *
 * jsdom 里节点量不出尺寸,所以节点按 React Flow 的服务端渲染写法直接给宽高和接点(`width` / `height` /
 * `handles`),和 ReferenceHintEdge.dom.test 同一个做法。两端同高的节点、同样的接点,画出来的贝塞尔
 * 是一条直线 —— 这正是「两根线在中段重合」的最坏情形,一个像素都藏不住。
 *
 * 两条断言钉住这一笔的两头:
 *  · **单条边逐字相同。** 同一串边,一边交给 React Flow 内置的 `default` / `smoothstep`,一边交给
 *    我们自己的边组件(道次 0),比 DOM(路径、命中带、类名)一个字符都不许差 —— 常态观感不许变。
 *  · **同一对节点两条边,两条 `d` 不一样。** 改动之前这两条完全重合(一根盖住另一根),这就是
 *    「顺序线回来了却糊在一起」。让开之后中段各走各的,两头仍旧钉在原来的接点上。
 */
import { cleanup, render } from "@testing-library/react";
import { Position, ReactFlow, ReactFlowProvider, type Edge, type Node } from "@xyflow/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { CANVAS_PARALLEL_EDGE_GAP, CANVAS_EDGE_TYPES, laneEdges } from "@/components/app/canvasEdgeShape";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(cleanup);

/** 一格:控制进 / 控制在左上右各一个(没有 id 的那两个),数据口在下面一行。 */
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
      { id: "in:text", type: "target", position: Position.Left, x: 0, y: 45, width: 9, height: 9 },
      { id: "out:text", type: "source", position: Position.Right, x: 151, y: 45, width: 9, height: 9 },
    ],
  };
}

/** 把这一串边画出来。`customTypes` 为假就是**改动前**那一路:React Flow 内置的两种线。 */
function flowWith(edges: Edge[], customTypes: boolean) {
  const view = render(
    <ReactFlowProvider>
      <div style={{ width: 800, height: 400 }}>
        <ReactFlow
          //: 两个实例给同一个 id:箭头、无障碍那几处行内属性里带着它,逐字比对才比得下去。
          id="probe"
          nodes={[box("a", 0), box("b", 400)]}
          edges={edges}
          {...(customTypes ? { edgeTypes: CANVAS_EDGE_TYPES } : {})}
        />
      </div>
    </ReactFlowProvider>,
  );
  const group = (id: string) => view.container.querySelector<SVGGElement>(`.react-flow__edge[data-id="${id}"]`);
  const path = (id: string) => group(id)?.querySelector<SVGPathElement>(".react-flow__edge-path")?.getAttribute("d") ?? "";
  return {
    view,
    group,
    path,
    /** 这个 `<g>` 里画出来的东西(路径、命中带、线上那行字)。 */
    drawn: (id: string) => group(id)?.innerHTML ?? "",
    classes: (id: string) => group(id)?.getAttribute("class") ?? "",
  };
}

/** `d` 开头那个点(`M` 后面、第一条曲线命令之前)。 */
const startOf = (d: string) => /^M([-\d.,\s]+?)(?=[CLQ])/.exec(d)?.[1].trim() ?? "";

const control: Edge = { id: "e-a-b", source: "a", target: "b", type: "default" };
const data: Edge = { id: "d-a-text-b-text", source: "a", target: "b", sourceHandle: "out:text", targetHandle: "in:text", type: "default" };
/** 同一对节点、**同一个接口**上的第二条数据边(审计里「2–3 条数据边」的那一族)。 */
const data2: Edge = { ...data, id: "d-a-json-b-text" };

describe("单条边:画出来和改动前逐字相同", () => {
  for (const shape of ["default", "smoothstep"] as const) {
    it(`${shape}:换成我们自己的边组件,路径 / 命中带 / 类名一个字符都不差`, () => {
      const edges = laneEdges([{ ...control, type: shape }]);
      const before = flowWith(edges, false);
      const beforeDrawn = before.drawn("e-a-b");
      const beforeClasses = before.classes("e-a-b");
      const beforePath = before.path("e-a-b");
      cleanup();
      const after = flowWith(edges, true);
      expect(after.path("e-a-b")).toBe(beforePath);
      expect(after.drawn("e-a-b")).toBe(beforeDrawn);
      expect(after.classes("e-a-b")).toBe(beforeClasses);
    });
  }
});

describe("同一对节点多条边:两条都看得见", () => {
  it("两条同端点的数据边:两条 `d` 不一样,中段各让半格,两头仍旧同一个接点", () => {
    const raw = [data2, data];
    const noLane = flowWith(raw, true);
    //: 改动之前(道次 0):两条完全重合 —— 一根盖住另一根。
    expect(noLane.path(data.id)).toBe(noLane.path(data2.id));
    const starts = noLane.path(data.id) && startOf(noLane.path(data.id));
    cleanup();

    const shown = flowWith(laneEdges(raw), true);
    expect(shown.path(data.id)).not.toBe(shown.path(data2.id));
    //: 让开的只有中段:两头还是原来那个数。
    expect(startOf(shown.path(data.id))).toBe(starts);
    expect(startOf(shown.path(data2.id))).toBe(starts);
    //: 两条各让半格,中段整好差一格。
    const midY = (d: string) => {
      const found = /^M([-\d.]+),([-\d.]+) C([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+) ([-\d.]+),([-\d.]+)$/.exec(d);
      if (!found) throw new Error(`不是贝塞尔的 d:${d}`);
      return (Number(found[2]) + 3 * Number(found[4]) + 3 * Number(found[6]) + Number(found[8])) / 8;
    };
    expect(Math.abs(midY(shown.path(data.id)) - midY(shown.path(data2.id)))).toBeCloseTo(CANVAS_PARALLEL_EDGE_GAP, 9);
  });

  it("控制线 + 数据线(同一对节点):两条都画出来,路径不一样", () => {
    const shown = flowWith(laneEdges([control, data]), true);
    expect(shown.path(control.id)).not.toBe("");
    expect(shown.path(data.id)).not.toBe("");
    expect(shown.path(control.id)).not.toBe(shown.path(data.id));
  });

  it("平滑折线那一档也一样:两条 `d` 不一样,两头不动", () => {
    const first: Edge = { ...control, type: "smoothstep" };
    const second: Edge = { ...data, type: "smoothstep" };
    const noLane = flowWith([first, second], true);
    const starts = new Map([first, second].map((edge) => [edge.id, startOf(noLane.path(edge.id))]));
    cleanup();
    const shown = flowWith(laneEdges([first, second]), true);
    expect(shown.path(first.id)).not.toBe(shown.path(second.id));
    //: 两头钉在各自的接点上:控制线走的是 25 那个口,数据线走 45 那个口,让开之后都还在原处。
    expect(startOf(shown.path(first.id))).toBe(starts.get(first.id));
    expect(startOf(shown.path(second.id))).toBe(starts.get(second.id));
    expect(starts.get(first.id)).not.toBe(starts.get(second.id));
  });

  it("三条:三条 `d` 两两不同;中间那条(道次 0)和单独画它时**逐字相同**", () => {
    const left: Edge = { ...data2, id: "d-a-json-b-text" };
    const middle: Edge = { ...data, id: "d-a-mid-b-text" };
    const right: Edge = { ...data, id: "d-a-text-b-other" };
    const alone = flowWith([middle], true);
    const middleAlone = alone.path(middle.id);
    cleanup();
    const shown = flowWith(laneEdges([middle, right, left]), true);
    const drawn = [shown.path(left.id), shown.path(middle.id), shown.path(right.id)];
    expect(new Set(drawn).size).toBe(3);
    expect(shown.path(middle.id)).toBe(middleAlone);
  });
});
