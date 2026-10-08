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
  useI18n: () => (key: string) => (key === "wfIssuePluginUnusable" ? "插件节点不可用:{reason}"
    : key === "wfIssuePluginNeedsUpgrade" ? "用不了 · 需要升级:{reason}" : key),
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
      ? (asked.push(url), [{ type: "plugin.comfy.upscale", reason: "连接「我的 ComfyUI」没有勾选这个工具" },
                           { type: "plugin.comfy.wf_0ef16828a002_app", reason: "krea2 的表单还是旧格式", upgrade: true,
                             instance_id: "i1" }])
      : url.includes("/api/plugins") ? [{ id: "dev.mosael.comfyui", instances: [{ id: "i1", name: "我的 ComfyUI" }] }]
      : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
});

function inspect(node: { id: string; type: string; config: Record<string, unknown> }) {
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

it("检查器顶部说后端给的真实原因", async () => {
  inspect({ id: "p1", type: "plugin.comfy.upscale", config: {} });
  expect(await screen.findByText("插件节点不可用:连接「我的 ComfyUI」没有勾选这个工具")).toBeTruthy();
  expect(asked.some((url) => url.includes("types=plugin.comfy.upscale"))).toBe(true);
  expect(document.querySelector("[data-node-upgrade]"), "修法不是升级:不给升级的按钮").toBeNull();
});

//: ADR 0045 修订之二(D1 / D64):工作流里指着旧格式表单工具的节点,标成「用不了 · 需要升级」,就地给去工作流库升级的那颗
it("修法是升级的:说「用不了 · 需要升级」,给「去工作流库升级」", async () => {
  inspect({ id: "p2", type: "plugin.comfy.wf_0ef16828a002_app", config: {} });
  expect(await screen.findByText("用不了 · 需要升级:krea2 的表单还是旧格式")).toBeTruthy();
  const button = await screen.findByRole("button", { name: "genModelMissingUpgrade" });
  expect(button.closest("[data-node-upgrade]")).toBeTruthy();
});
