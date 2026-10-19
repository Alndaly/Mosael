/** @vitest-environment jsdom */
/**
 * 画布视口:**量不出宽高的时候不许做带动画的跳转。**
 *
 * d3-zoom 的过渡拿 extent 的跨度当插值尺度(见 d3-zoom 的 `schedule`:`w / l[2]`)。容器是
 * 0×0 时跨度是 0,于是 `0 / 0 = NaN`,过渡中的每一帧都把 transform 的三个分量写成 NaN,
 * React Flow 的 `<Background>` 再把它写进 `<pattern x/y>` 和圆点的 `cx/cy/r` —— CI 日志里那串
 * 「Received NaN for the `cx` attribute」就是这么来的。
 *
 * 0×0 不是只在测试里出现:容器还没挂上、右栏展开把画布压没、窗口窄到 0,量出来都是 0。
 * 所以兜底放在**算坐标 / 视口的那一层**(`fitCanvasViewport` / `centerCanvasViewport`):
 * 没尺寸就不摆动画、直接跳过去。**不在 JSX 里到处塞 `|| 0`** —— 那只是把 NaN 藏起来。
 */
import { act, render, waitFor } from "@testing-library/react";
import { Background, ReactFlow, type ReactFlowInstance } from "@xyflow/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

import { fitCanvasViewport } from "./fitCanvasViewport";

const NODE = { id: "n1", position: { x: 40, y: 60 }, data: { label: "n" }, width: 220, height: 140 };

//: jsdom 没有 ResizeObserver;React Flow 的尺寸钩子在挂载时会 new 一个。这里要测的不是重排,
//: 是「量出来是 0」时视口跳转怎么走,所以给一个不回调的桩即可(和 boards 那几条 DOM 用例同一套装置)。
beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

function Canvas({ capture }: { capture: (target: HTMLDivElement, instance: ReactFlowInstance) => void }) {
  const surface = React.useRef<HTMLDivElement | null>(null);
  return (
    <div ref={surface} data-zero-surface="" style={{ width: 0, height: 0 }}>
      <div style={{ width: 800, height: 600 }}>
        <ReactFlow
          defaultNodes={[NODE]}
          defaultEdges={[]}
          minZoom={0.1}
          maxZoom={2}
          onInit={(instance) => {
            //: React Flow 的实例类型跟着这份 defaultNodes 的具体形状走;这里只用到视口那几个方法,
            //: 和 `fitCanvasViewport` 的参数同一个类型面。
            if (surface.current) capture(surface.current, instance as unknown as ReactFlowInstance);
          }}
        >
          <Background />
        </ReactFlow>
      </div>
    </div>
  );
}

/** 记录**曾经**被写进 DOM 的 NaN 坐标:过渡到一半会被下一帧覆盖回正常值,只看最后一帧会漏。 */
function watchNaN(): { seen: string[]; stop: () => void } {
  const seen: string[] = [];
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "attributes" || !mutation.attributeName) continue;
      const element = mutation.target as Element;
      if (element.getAttribute(mutation.attributeName) === "NaN") {
        seen.push(`${element.tagName.toLowerCase()}.${mutation.attributeName}`);
      }
    }
  });
  observer.observe(document.body, {
    subtree: true,
    attributes: true,
    attributeFilter: ["cx", "cy", "r", "x", "y"],
  });
  return { seen, stop: () => observer.disconnect() };
}

it("容器量不出宽高时跳转直接落地:不出现 NaN 坐标,也没有 React 的 NaN 警告", async () => {
  const warnings: string[] = [];
  const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    const text = args.map((one) => String(one)).join(" ");
    if (text.includes("NaN")) warnings.push(text);
  });
  const { seen, stop } = watchNaN();
  let captured: { surface: HTMLDivElement; instance: ReactFlowInstance } | null = null;

  try {
    render(<Canvas capture={(surface, instance) => { captured = { surface, instance }; }} />);
    await waitFor(() => expect(captured).not.toBeNull());

    //: `waitFor` 里已经断言过它不是 null(回调里赋值,TS 看不到这条数据流)。
    const { surface, instance } = captured!;
    expect(surface.clientWidth).toBe(0);

    //: 和真实调用同一个入口、同一个 240ms:量不出尺寸时它**不该**起过渡。
    await act(async () => {
      await fitCanvasViewport(instance, surface, {}, { duration: 240 });
    });

    const viewport = instance.getViewport();
    expect(Number.isFinite(viewport.x) && Number.isFinite(viewport.y) && Number.isFinite(viewport.zoom)).toBe(true);
    expect(seen).toEqual([]);
    expect(warnings).toEqual([]);
    expect(
      document.querySelector('circle[cx="NaN"], circle[cy="NaN"], circle[r="NaN"], pattern[x="NaN"], pattern[y="NaN"]'),
    ).toBeNull();
  } finally {
    stop();
    spy.mockRestore();
  }
});
