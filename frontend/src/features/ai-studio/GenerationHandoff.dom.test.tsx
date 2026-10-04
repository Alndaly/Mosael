/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 模型库的「用它生成」交过来的:生成页清单到了之后选中那张工作流、选模型文件的那一格填上这个文件、LoRA 的触发词
 * 接在提示词末尾 —— 点「生成」发出去的就是它们。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { handOffToGeneration, takeGenerationHandoff } from "@/lib/generationHandoff";

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
  takeGenerationHandoff(["image", "video", "audio"]);
});
beforeEach(() => {
  localStorage.clear();
});

const OPENAI = {
  id: "p1:image:gpt-image-1", provider_profile_id: "p1", profile_name: "OpenAI", provider: "openai", kind: "image",
  model: "gpt-image-1", label: "OpenAI · gpt-image-1", capabilities: { modes: ["text-to-image"], parameter_keys: [] },
  capabilities_known: true, adapter_available: true, is_default: true,
};
const PORTRAIT = {
  id: "p9:image:portrait.json", provider_profile_id: "p9", profile_name: "ComfyUI", provider: "plugin:dev.mosael.comfyui",
  kind: "image", model: "portrait.json", label: "ComfyUI · portrait", plugin_instance_id: "i1",
  capabilities: {
    modes: ["text-to-image"],
    parameter_keys: ["9.lora_name"],
    parameter_schema: {
      "9.lora_name": { type: "string", title: "LoRA", enum: ["detail.safetensors", "anima_style.safetensors"], "x-model-folder": "loras" },
    },
  },
  capabilities_known: true, adapter_available: true, is_default: false,
};

function renderStudio() {
  const posts: Array<{ url: string; body: unknown }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") {
      posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : null });
      if (url.includes("/api/generation/sessions")) return json({ id: "s-new", workspace_id: "w1", kind: "image", title: "", is_mine: true });
      return json({ id: "g1", job_id: "j1" });
    }
    if (url.includes("/api/generation/options?kind=image")) return json([OPENAI, PORTRAIT]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/model-library")) return json({ folders: [], models: [], missing: [], download: { route: "none", note: "" }, downloads: [] });
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { posts };
}

describe("模型库交过来的「用它生成」", () => {
  it("选中那张工作流、那一格填上这个文件、触发词接在提示词末尾;点「生成」发出去的就是它们", async () => {
    handOffToGeneration({
      providerProfileId: "p9",
      kind: "image",
      model: "portrait.json",
      declared: { "9.lora_name": "anima_style.safetensors" },
      promptWords: ["anima style"],
    });
    const { posts } = renderStudio();
    const prompt = (await screen.findByRole("textbox", { name: "genPromptLabel" })) as HTMLTextAreaElement;
    await waitFor(() => expect(prompt.value).toBe("anima style"));
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs") || one.url.includes("/generations"))).toBe(true));
    const sent = JSON.stringify(posts.map((one) => one.body));
    expect(sent).toContain('"model":"portrait.json"');
    expect(sent).toContain('"provider_profile_id":"p9"');
    expect(sent).toContain('"9.lora_name":"anima_style.safetensors"');
  });

  it("没人交东西过来:照旧落在默认模型上", async () => {
    localStorage.setItem("mosael:tab:ai-studio", "generate");
    const { posts } = renderStudio();
    const prompt = (await screen.findByRole("textbox", { name: "genPromptLabel" })) as HTMLTextAreaElement;
    expect(prompt.value).toBe("");
    fireEvent.change(prompt, { target: { value: "海边" } });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.length).toBeGreaterThan(0));
    expect(JSON.stringify(posts.map((one) => one.body))).toContain('"model":"gpt-image-1"');
  });
});
