/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 「AI 生成素材」节点换模型时参数留下哪几项。此前一律清空:官方模板按开始参数接好的画幅、分辨率绑定
 * (`{{input.aspect_ratio}}`)一换模型全没了,改开始节点的画幅从此不起作用。现在新模型仍收的键里,
 * 绑定原样留着;写死的值只在新模型的可选值里还有它时才留。
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

const PROFILE = {
  id: "p1", vendor: "bytedance", enabled: true, auth_type: "api_key", oauth_linked: false, base_url: "", capability_ids: ["video"],
};

function option(model: string, capabilities: Record<string, unknown>) {
  return {
    id: `p1:video:${model}`, provider_profile_id: "p1", profile_name: "P", label: model, provider: "bytedance", model, model_label: model,
    kind: "video", capabilities, capabilities_known: true, adapter_available: true, is_default: false,
  };
}

const SEEDANCE = option("seedance", {
  parameter_keys: ["aspect_ratio", "resolution", "duration_seconds", "seed", "first_frame"],
  aspect_ratios: ["16:9", "9:16", "1:1"], resolutions: ["480p", "720p"], duration_seconds: [5, 10],
});
//: 收画幅、分辨率、时长,但只收 4 / 6 / 8 秒、不收种子。
const VEO = option("veo", {
  parameter_keys: ["aspect_ratio", "resolution", "duration_seconds", "first_frame"],
  aspect_ratios: ["16:9", "9:16"], resolutions: ["720p", "1080p"], duration_seconds: [4, 6, 8],
});

function renderInspector(parameters: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/settings/providers")) body = [PROFILE];
    if (url.pathname.endsWith("/generation/options") && url.searchParams.get("kind") === "video") body = [SEEDANCE, VEO];
    if (url.pathname.endsWith("/api/assets")) body = { items: [], next_cursor: null, total: 0 };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const node = {
    id: "clip", type: "ai_generate", position: { x: 0, y: 0 },
    config: { provider_profile_id: "p1", provider: "bytedance", model: "seedance", kind: "video", prompt: "p", parameters },
  };
  const onChange = vi.fn();
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
            onChange={onChange}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return onChange;
}

async function pickModel(name: string) {
  const trigger = await waitFor(() => {
    const found = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("seedance"));
    if (!found) throw new Error("model picker not ready");
    return found;
  });
  fireEvent.click(trigger);
  //: 清单一行两层:主名(模型名)在前,第二行是连接名(ADR 0045)
  fireEvent.click(await screen.findByRole("option", { name: new RegExp(`^${name}`) }));
}

describe("AI 生成节点换模型", () => {
  it("模板接好的绑定留着,新模型不收的值和键丢掉", async () => {
    const onChange = renderInspector({
      aspect_ratio: "{{input.aspect_ratio}}",
      resolution: "{{input.resolution}}",
      duration_seconds: 5,
      seed: 7,
    });
    await pickModel("veo");
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const config = onChange.mock.calls.at(-1)![0].config;
    expect(config.model).toBe("veo");
    expect(config.parameters).toEqual({ aspect_ratio: "{{input.aspect_ratio}}", resolution: "{{input.resolution}}" });
  });

  it("写死的值新模型也收:照留", async () => {
    const onChange = renderInspector({ aspect_ratio: "9:16", resolution: "720p" });
    await pickModel("veo");
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(onChange.mock.calls.at(-1)![0].config.parameters).toEqual({ aspect_ratio: "9:16", resolution: "720p" });
  });
});
