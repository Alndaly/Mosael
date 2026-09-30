/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

/**
 * 插件节点用不了时,检查器顶部说**后端给的真实原因**(没装、没接、连接停用、工具没勾选……),
 * 而不是那句笼统的「没装、已停用或工具已不在」—— 该去的地方各不相同。
 */

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "wfIssuePluginUnusable" ? "插件节点不可用:{reason}" : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReactFlowProvider } from "@xyflow/react";

import type { WorkflowGraph } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

const asked: string[] = [];

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/workflows/node-types/unusable")
      ? (asked.push(url), [{ type: "plugin.comfy.upscale", reason: "连接「我的 ComfyUI」没有勾选这个工具" }])
      : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
});

it("检查器顶部说后端给的真实原因", async () => {
  const node = { id: "p1", type: "plugin.comfy.upscale", config: {} };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node}
            meta={null}
            graph={{ nodes: [node], edges: [] } as WorkflowGraph}
            registry={new Map()}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("插件节点不可用:连接「我的 ComfyUI」没有勾选这个工具")).toBeTruthy();
  expect(asked.some((url) => url.includes("types=plugin.comfy.upscale"))).toBe(true);
});
