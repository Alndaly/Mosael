/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 字段里存的值要**原样显示出来,改了也原样存回去**。
 *
 * 这里的节点类型名是假的 —— 控件跟着字段声明的类型走,不认识具体节点。
 */

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReactFlowProvider } from "@xyflow/react";

import type { WorkflowNodeType } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
});

const META = {
  type: "make_canvas",
  label: "建画布",
  description: "",
  category: "",
  config: {
    width: { type: "number", label: "宽" },
    fps: { type: "number", label: "帧率" },
    mode: { type: "string", label: "模式", options: ["a", "b"], option_labels: { a: "甲", b: "乙" }, allow_custom: true },
    kind: { type: "string", label: "种类", options: ["x", "y"], option_labels: { x: "叉", y: "歪" } },
  },
  outputs: [],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

function renderInspector(config: Record<string, unknown>) {
  const onChange = vi.fn();
  const node = { id: "n1", type: META.type, position: { x: 0, y: 0 }, config };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={META}
            graph={{ nodes: [node], edges: [] } as never}
            registry={new Map([[META.type, META]])}
            workspaceId="w1"
            onChange={onChange}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const field = (key: string) => document.querySelector<HTMLInputElement>(`[data-field-key="${key}"] input`)!;
  const box = (key: string) => document.querySelector<HTMLElement>(`[data-field-key="${key}"]`)!;
  return { onChange, field, box };
}

describe("数字字段", () => {
  //: 官方模板就这么写:新建时间线的宽高帧率跟着源视频走。引擎对每个字段都做插值,
  //: 所以数字字段装一条引用是合法的 —— 而 <input type="number"> 会把它当非法值清成空串,
  //: 面板上看着是「没填」,用户顺手填个数字就把引用覆盖掉了。
  it("装着上游引用时原样显示", () => {
    const { field } = renderInspector({ width: "{{source_video.width}}", fps: 30 });
    expect(field("width").value).toBe("{{source_video.width}}");
    expect(field("fps").value).toBe("30");
  });

  it("填数字照常存", () => {
    const { field, onChange } = renderInspector({ width: "", fps: "" });
    fireEvent.change(field("width"), { target: { value: "1080" } });
    // 打字是这个字段的一串(撤销时塌成一条)。
    expect(onChange).toHaveBeenLastCalledWith({ config: { width: "1080", fps: "" } }, { coalesce: "n1.width" });
  });
});

describe("带固定选项的字段", () => {
  Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {}, scrollIntoView: () => {} });

  //: 声明了 allow_custom 的(生成节点的 source_group、白模渲染的 render):整片流程里是逐镜
  //: 决定的,官方模板写的是 `{{loop.item.reference_mode}}`。此前面板对「有固定选项」的字段
  //: 一律给纯下拉,不认 allow_custom —— 引用显示成空白,也填不回去。
  it("声明了能手填的:引用原样显示,也能手填", async () => {
    const user = userEvent.setup();
    const { box, onChange } = renderInspector({ mode: "{{loop.item.mode}}", kind: "x" });
    const trigger = within(box("mode")).getByRole("combobox");
    expect(trigger.textContent).toContain("{{loop.item.mode}}");
    await user.click(trigger);
    await user.keyboard("{{{{shot.mode}}");
    await user.click(await screen.findByText(/comboboxUseCustomValue/));
    // 手填完点「使用」是一次提交,离散的一步。
    expect(onChange).toHaveBeenLastCalledWith({ config: { mode: "{{shot.mode}}", kind: "x" } }, undefined);
  });

  it("没声明的仍是纯下拉,显示选项的名字", () => {
    const { box } = renderInspector({ mode: "a", kind: "x" });
    expect(within(box("kind")).getByRole("combobox").textContent).toContain("叉");
    expect(within(box("mode")).getByRole("combobox").textContent).toContain("甲");
  });
});
