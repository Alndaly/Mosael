/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

/**
 * 节点说明和字段帮助来自后端的文案目录和插件清单,写着 `**新素材**`、`` `素材id` `` ——
 * 检查器上按格式渲染,不露记号。
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
  type: "denoise_audio",
  label: "降噪",
  description: "产出一份**新素材**,原素材不动",
  category: "",
  config: {
    source_assets: { type: "string", label: "素材", description: "每行一条 `素材id` 或 `素材id:角色`" },
  },
  outputs: [],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

it("字段帮助和节点说明里的记号渲染成格式", async () => {
  const node = { id: "n1", type: META.type, position: { x: 0, y: 0 }, config: {} };
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider delayDuration={0}>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={META}
            graph={{ nodes: [node], edges: [] } as never}
            registry={new Map([[META.type, META]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  expect(screen.getByText("素材id").tagName).toBe("CODE");
  expect(container.textContent).not.toMatch(/\*\*|`/);

  // 节点说明在图标的提示气泡里:聚焦触发器把它打开。
  const trigger = container.querySelector("[data-state][class*='cursor-help']") as HTMLElement;
  fireEvent.focus(trigger);
  const strong = await screen.findAllByText("新素材");
  expect(strong.some((node) => node.tagName === "STRONG")).toBe(true);
  expect(document.body.textContent).not.toContain("**");
});
