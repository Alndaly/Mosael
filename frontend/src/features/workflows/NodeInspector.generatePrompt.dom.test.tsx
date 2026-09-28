/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  askedPaths.length = 0;
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

const COMFY_PROFILE = {
  id: "p1", vendor: "plugin:dev.mosael.comfyui", enabled: true, auth_type: "api_key", oauth_linked: false,
  base_url: "http://127.0.0.1:8188", capability_ids: ["image"],
};

const askedPaths: string[] = [];

function renderInspector(
  capabilities: Record<string, unknown>,
  {
    profiles = [COMFY_PROFILE],
    config,
    modelsListed = true,
  }: { profiles?: unknown[]; config?: Record<string, unknown>; modelsListed?: boolean } = {},
) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    askedPaths.push(url.pathname);
    let body: unknown = [];
    if (url.pathname.endsWith("/settings/providers")) body = profiles;
    if (url.pathname.endsWith("/api/assets")) body = [{ id: "a1", kind: "image", name: "产品图", original_filename: "p.png" }];
    if (modelsListed && url.pathname.endsWith("/generation/options") && url.searchParams.get("kind") === "image") {
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
    config: config ?? { provider_profile_id: "p1", provider: "plugin:dev.mosael.comfyui", model: "upscale.json", kind: "image", prompt: "" },
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

describe("AI 生成节点顶部的配置提醒", () => {
  const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

  //: 后端只在 provider / model 为空时才取默认(generation/operations.create_generation_job)。
  it("节点已选好模型:不提示「还没有默认供应商与模型」", async () => {
    renderInspector({ parameter_keys: ["seed"], prompt: "optional" });
    await waitFor(() => expect(screen.getByText("wfGenPromptOptional")).toBeInTheDocument());
    await settle();
    expect(screen.queryByText("aiCapabilityNotConfigured")).toBeNull();
    expect(screen.queryByText("wfIssueGenUnconfigured")).toBeNull();
  });

  it("节点没选模型、也没有默认:才提示去配默认", async () => {
    renderInspector({ parameter_keys: ["seed"] }, { config: { kind: "image", prompt: "" } });
    await waitFor(() => expect(screen.getByText("aiCapabilityNotConfigured")).toBeInTheDocument());
  });

  //: 和就绪清单同一个判定(bindingReadiness.generationVendors):清单判「服务商没配」的,这里也说。
  //: 判据是后端给的可用生成模型(和 AI 工作台同源),不是连接开没开:连接开着而模型全停了,
  //: 后端不列它的模型,AI 工作台说「没配置」,这里也得这么说。
  it("连接启用但所选服务商下没有可用的生成模型:和就绪清单、AI 工作台一样报「没配」", async () => {
    renderInspector({ parameter_keys: ["seed"] }, { modelsListed: false });
    await waitFor(() => expect(screen.getByText("wfIssueGenUnconfigured")).toBeInTheDocument());
  });
});

//: 「输入素材」那几格是检查器自己画的专区,读的是字段选项里的素材清单。此前清单只在节点**声明了**
//: asset 型字段时才拉,而生成节点一个也没有 —— 下拉永远是空的。现在由画着这几格的检查器说它要。
describe("AI 生成节点的输入素材", () => {
  it("模型收参考图:那一格的下拉里有工作区素材", async () => {
    renderInspector({ parameter_keys: ["reference_image"] });
    await waitFor(() => expect(askedPaths).toContain("/api/assets"));
    const trigger = (await screen.findByText("wfGenSourcePlaceholder")).closest<HTMLElement>('[role="combobox"]')!;
    fireEvent.click(trigger);
    expect(await screen.findByText("产品图")).toBeInTheDocument();
  });

  it("模型不收任何素材:不去拉素材清单", async () => {
    renderInspector({ parameter_keys: ["seed"] });
    await waitFor(() => expect(askedPaths.some((path) => path.endsWith("/generation/options"))).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(askedPaths).not.toContain("/api/assets");
  });
});
