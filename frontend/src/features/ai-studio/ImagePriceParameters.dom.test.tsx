/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 生图的画质和分辨率档决定价钱:Evolink 上的 GPT Image 2 按 token 计费,1K 低画质约 $0.0053 一张,2K 高画质约
 * $0.386。此前 AI 工作台只给视频摆「分辨率」、图像这一支也不发它 —— 声明了分辨率档的生图模型选不了、发不出,
 * 落在服务商的默认值上;画质的价差也没有一句话说明。
 *
 * 钉住的是:生图模型声明了 resolution 就摆出来、默认取模型说的那档、提交时发出去;画质照模型声明的默认值
 * (最便宜的 low)发,控件下面说清价差。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
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
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
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

const GPT_IMAGE_2 = {
  modes: ["text-to-image", "image-to-image"],
  parameter_keys: ["size", "resolution", "num_images", "quality"],
  parameter_choices: { quality: ["low", "medium", "high"] },
  default_quality: "low",
  resolutions: ["1K", "2K", "4K"],
  default_resolution: "1K",
  sizes: ["auto", "1:1", "16:9"],
  default_size: "1:1",
  max_num_images: 10,
};

const SESSION = { id: "s1", workspace_id: "w1", title: "会话", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };

function renderStudio() {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return json({ generation: { id: "g-new" }, job: { id: "j-new", status: "queued" } });
    }
    if (init?.method === "PATCH") return json(SESSION);
    if (url.includes("/api/generation/options?kind=image")) {
      return json([{
        id: "p1:image:gpt-image-2", provider_profile_id: "p1", profile_name: "Evolink AI", provider: "evolink",
        kind: "image", model: "gpt-image-2", label: "Evolink AI · gpt-image-2", capabilities: GPT_IMAGE_2,
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
  return { posts };
}

describe("生图的画质和分辨率档", () => {
  it("声明了分辨率档的生图模型摆出分辨率,默认取模型说的那档;画质下面说清价差;提交时两项都发", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio();
    expect(await screen.findByText("genResolution")).toBeInTheDocument();
    expect(screen.getByText("genQuality")).toBeInTheDocument();
    expect(screen.getByText("genQualityPriceHint")).toBeInTheDocument();

    await user.type(await screen.findByRole("textbox", { name: "genPromptLabel" }), "一只猫");
    const submit = screen.getByRole("button", { name: "generate" });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);
    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    const body = posts.find((one) => one.url.includes("/api/generation/jobs"))!.body;
    expect(body.parameters).toMatchObject({ size: "1:1", resolution: "1K", quality: "low" });
  });
});
