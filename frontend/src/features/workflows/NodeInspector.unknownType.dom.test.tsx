/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

/**
 * 插件没装 / 停用了,目录里就没有这种节点:检查器此前一个字段都画不出来,也不说为什么,
 * 头上只有一个裸的 `plugin.包.工具`。
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

import type { WorkflowGraph } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
});

function renderInspector(type: string) {
  const node = { id: "p1", type, config: {} };
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
}

it("插件节点不在目录里:检查器说是插件不可用", () => {
  renderInspector("plugin.comfy.upscale");
  expect(screen.getByText("wfIssuePluginUnavailable")).toBeTruthy();
});

it("认不出的非插件类型:说是未知类型", () => {
  renderInspector("gone_node");
  expect(screen.getByText("wfIssueUnknownType")).toBeTruthy();
});
