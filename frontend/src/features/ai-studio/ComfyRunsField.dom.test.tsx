/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

/**
 * ComfyUI 的工作流「张数」是**跑几遍**(维护者拍板):每遍按工作流原样出它那一批(画布存着一次 4 张就是 4 张)。只写「张数」
 * 会被读成「一共几张」,所以 AI 工作台里这一格叫「跑几遍」,下面一句话说清一遍出几张、这次一共几张。别的模型照旧叫「张数」。
 */

const MESSAGES: Record<string, string> = {
  genRuns: "跑几遍",
  genRunsHint: "跑几遍。每遍按工作流原样出 {perRun} 张({detail}),这次一共 {total} 张",
  genRunsDetailBatch: "批量 {batch}",
};
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => MESSAGES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
});

const SESSION = { id: "s1", workspace_id: "w1", title: "会话", origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };

function renderStudio(capabilities: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/options?kind=image")) {
      return json([{
        id: "p1:image:古风女孩1.json", provider_profile_id: "p1", profile_name: "ComfyUI", provider: "plugin:dev.mosael.comfyui",
        kind: "image", model: "古风女孩1.json", label: "古风女孩1 · ComfyUI", capabilities,
        capabilities_known: true, adapter_available: true, is_default: true,
      }]);
    }
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([SESSION]);
    return json([]);
  }) as never;
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
}

it("ComfyUI 的工作流:这一格叫「跑几遍」,下面说一遍几张、这次一共几张", async () => {
  renderStudio({
    modes: ["text-to-image"], prompt: "optional", parameter_keys: ["num_images"], max_num_images: 4,
    num_images_unit: "runs", batch_per_run: 4, outputs_per_run: 4,
  });
  expect(await screen.findByText("跑几遍")).toBeInTheDocument();
  expect(screen.getByText("跑几遍。每遍按工作流原样出 4 张(批量 4),这次一共 4 张")).toBeInTheDocument();
  expect(screen.queryByText("wfGenNumImages")).not.toBeInTheDocument();
});

it("别的模型照旧叫「张数」,不带这句说明", async () => {
  renderStudio({ modes: ["text-to-image"], parameter_keys: ["num_images"], max_num_images: 4 });
  expect(await screen.findByText("wfGenNumImages")).toBeInTheDocument();
  expect(screen.queryByText("跑几遍")).not.toBeInTheDocument();
});
