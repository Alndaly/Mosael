/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render } from "@testing-library/react";
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
  return { onChange, field };
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
    expect(onChange).toHaveBeenLastCalledWith({ config: { width: "1080", fps: "" } });
  });
});
