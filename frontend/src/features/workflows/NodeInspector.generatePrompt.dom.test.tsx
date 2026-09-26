/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 工作流「AI 生成素材」节点里,「提示词」一格照**选中的模型**摆(描述符的 `prompt`):
 * 不收提示词的(放大工作流)整格藏起来;可以不写的说一句「可以不写」、不标必填;没说的标必填。
 * 节点声明里不再写死必填 —— 那是按模型变的。
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

import { TooltipProvider } from "@/components/ui/tooltip";

import { NodeInspector } from "@/features/workflows/WorkflowsView";
import type { WorkflowNodeType } from "@/api/client";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  cleanup();
});

const META = {
  type: "ai_generate",
  label: "AI 生成素材",
  description: "",
  category: "",
  config: {
    provider_profile_id: { type: "string" },
    provider: { type: "string", required: true },
    model: { type: "string", required: true, depends_on: "provider" },
    kind: { type: "string", required: true, options: ["image", "video", "audio"] },
    prompt: { type: "template", label: "提示词" },
    parameters: { type: "object" },
    source_assets: { type: "template", lines: true },
  },
  outputs: ["asset_id"],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

function renderInspector(capabilities: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/generation/options") && url.searchParams.get("kind") === "image") {
      body = [{
        id: "p1:image:upscale.json", provider_profile_id: "p1", profile_name: "ComfyUI", label: "ComfyUI · 放大",
        provider: "plugin:dev.mosael.comfyui", model: "upscale.json", kind: "image", capabilities,
        capabilities_known: true, adapter_available: true, is_default: true,
      }];
    }
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const node = {
    id: "gen", type: "ai_generate", position: { x: 0, y: 0 },
    config: { provider_profile_id: "p1", provider: "plugin:dev.mosael.comfyui", model: "upscale.json", kind: "image", prompt: "" },
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={META}
            graph={{ nodes: [node], edges: [] } as never}
            registry={new Map([["ai_generate", META]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const promptField = () => document.querySelector<HTMLElement>('[data-field-key="prompt"]');

describe("AI 生成节点的提示词一格", () => {
  it("选中的模型不收提示词:整格藏起来", async () => {
    renderInspector({ parameter_keys: ["reference_image"], prompt: "none" });
    // 模型清单到之前按要写摆(那一格在);到了之后才知道它不收,整格收起。
    expect(promptField()).not.toBeNull();
    await waitFor(() => expect(promptField()).toBeNull());
  });

  it("可以不写:说一句可以不写,不标必填", async () => {
    renderInspector({ parameter_keys: ["reference_image"], prompt: "optional" });
    await waitFor(() => expect(screen.getByText("wfGenPromptOptional")).toBeInTheDocument());
    expect(promptField()).not.toBeNull();
    expect(promptField()!.querySelector("em")).toBeNull();
  });

  it("没说:标必填", async () => {
    renderInspector({ parameter_keys: ["seed"] });
    await waitFor(() => expect(promptField()?.querySelector("em")?.textContent).toBe("*"));
  });
});
