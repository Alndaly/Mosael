/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 提示词要不要写由模型说(描述符的 `prompt`:required / optional / none)。
 *
 * 钉住的是:不收提示词的模型(ComfyUI 的放大工作流)不摆提示词框、也不摆「优化提示词」,空着就能提交,
 * 发出去的提示词是空串(换模型之前框里写过的字也不跟着发,见 promptToSend 的单测);可以不写的模型框还在,占位说清「可选」,空着也能提交;
 * 没说的照旧要写。
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
  localStorage.setItem("mosael:tab:ai-studio", "generate");
});

function imageOption(model: string, capabilities: Record<string, unknown>) {
  return {
    id: `p1:image:${model}`,
    provider_profile_id: "p1",
    profile_name: "ComfyUI",
    provider: "plugin:dev.mosael.comfyui",
    kind: "image",
    model,
    label: `ComfyUI · ${model}`,
    capabilities,
    capabilities_known: true,
    adapter_available: true,
    is_default: true,
  };
}

const SESSION = { id: "s1", workspace_id: "w1", title: "会话", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };

function renderStudio(capabilities: Record<string, unknown>) {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return json({ generation: { id: "g-new" }, job: { id: "j-new", status: "queued" } });
    }
    if (init?.method === "PATCH") return json(SESSION);
    if (url.includes("/api/generation/options?kind=image")) return json([imageOption("upscale.json", capabilities)]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([SESSION]);
    if (url.includes("/api/generation/jobs")) return json([]);
    if (url.includes("/api/settings/providers")) return json([{ id: "p1", name: "ComfyUI", vendor: "plugin:dev.mosael.comfyui", enabled: true }]);
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

async function sentBody(posts: Array<{ url: string; body: Record<string, unknown> }>) {
  await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
  return posts.find((one) => one.url.includes("/api/generation/jobs"))!.body;
}

describe("提示词要不要写,照模型说的摆", () => {
  it("不收提示词的模型:不摆提示词框和优化按钮,空着就能提交,发出去的是空串", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio({ modes: ["image-to-image"], parameter_keys: [], prompt: "none" });
    expect(await screen.findByText("genPromptNotUsed")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "genPromptLabel" })).toBeNull();
    expect(screen.queryByRole("button", { name: /optimizePrompt/ })).toBeNull();
    const submit = screen.getByRole("button", { name: "generate" });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);
    expect(await sentBody(posts)).toMatchObject({ model: "upscale.json", prompt: "" });
  });

  it("可以不写的模型:框还在、占位说是可选,空着也能提交", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio({ modes: ["image-to-image"], parameter_keys: [], prompt: "optional" });
    const box = await screen.findByRole("textbox", { name: "genPromptLabel" });
    // 模型清单到了之后占位才换成「可选」(没到时按要写摆)
    await waitFor(() => expect(box).toHaveAttribute("placeholder", "promptPlaceholderOptional"));
    const submit = screen.getByRole("button", { name: "generate" });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);
    expect(await sentBody(posts)).toMatchObject({ prompt: "" });
  });

  it("没说的照旧要写:空着不能提交,写了才行", async () => {
    const user = userEvent.setup();
    renderStudio({ modes: ["text-to-image"], parameter_keys: [] });
    const box = await screen.findByRole("textbox", { name: "genPromptLabel" });
    expect(box).toHaveAttribute("placeholder", "promptPlaceholder");
    await waitFor(() => expect(screen.getAllByText("ComfyUI · upscale.json").length).toBeGreaterThan(0));
    const submit = screen.getByRole("button", { name: "generate" });
    expect(submit).toBeDisabled();
    await user.type(box, "一只猫");
    await waitFor(() => expect(submit).toBeEnabled());
  });
});
