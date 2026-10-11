/** @vitest-environment jsdom */

/**
 * 「引擎参数」里,表单上挑的那一格如果是**读素材的槽位**,就该画成传图的那一格 —— 不是文件名下拉。
 *
 * 维护者截图(2026-10-11):视频工作流 `常用/minimax-text-image-2-video` 的精简表单上,「首帧」「尾帧」是两个只有
 * `none` 的下拉 —— 因为描述符把 `49.image` / `50.image` 声明成了普通字符串枚举(服务器 `input` 目录里的文件名)。
 *
 * 根因在插件那一侧:读素材的节点此前只认一张**硬编码的类名表**(LoadImage 那几个),这个工作流用的是
 * `Optional Load Image`(自家节点包),于是它不算素材槽位、道具也没法接上去。现在按 ComfyUI 自己的上传标记
 * (`image_upload`,前端就是照它给下拉加一个上传按钮)通用地认(见 plugins/bundled/comfyui 的 graph._loader_of),
 * 描述符再把它在这张表单上叫什么(`source_keys`)报给界面 —— 这一条钉住界面确实照着画。
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { AiStudio } from "@/features/ai-studio/AiStudio";

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
  localStorage.setItem("mosael:tab:ai-studio-create-filter", "all");
});

/** 这张工作流的样子(缩到两条读图槽位):表上两项的 key 是「节点.输入名」。 */
const ENGINE = {
  id: "p1:video:常用/minimax-text-image-2-video.json#io4e5u", provider_profile_id: "p1", plugin_instance_id: "inst",
  profile_name: "演示", provider: "comfyui", kind: "video", model: "常用/minimax-text-image-2-video.json#io4e5u",
  model_label: "图文/文 快速生成视频", group: "常用", capabilities_known: true, adapter_available: true, is_default: true,
  capabilities: {
    modes: ["keyframes-to-video"],
    parameter_keys: ["prompt", "first_frame", "last_frame"],
    prompt: "optional",
    source_limits: { first_frame: 1, last_frame: 1 },
    source_labels: { first_frame: ["首帧"], last_frame: ["尾帧"] },
    source_keys: { first_frame: ["49.image"], last_frame: ["50.image"] },
    requires_source: [["first_frame"]],
    form: {
      title: "图文/文 快速生成视频",
      description: "",
      items: [{ key: "prompt", label: "提示词" }, { key: "49.image", label: "首帧" }, { key: "50.image", label: "尾帧" }],
    },
  },
};

function renderStudio() {
  const session = {
    id: "s1", workspace_id: "w1", title: "video", kind: "video", provider_profile_id: "p1", model: ENGINE.model,
    origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", is_mine: true, shared: false,
    created_at: "2026-10-11T00:00:00Z", updated_at: "2026-10-11T00:00:00Z",
  };
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/options")) return json([ENGINE]);
    if (url.includes("/api/generation/sessions")) return json([session]);
    if (url.includes("/api/tts/engines")) return json([]);
    if (url.includes("/api/tts/voices")) return json([]);
    if (url.includes("/api/tts/config")) return json({ engine: "f5-tts" });
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
}

describe("引擎参数:表单上的读图槽位", () => {
  it("「首帧」「尾帧」画成传图的那一格(有上传入口、有槽位名),不是只有 none 的下拉", async () => {
    renderStudio();
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    //: 首尾帧是一个控件(genKeyframes):左右两格各带自己的名字,每格一个传图入口
    expect(await within(panel).findByText("genKeyframes")).toBeTruthy();
    await waitFor(() => expect(panel.querySelectorAll('input[type="file"]').length).toBeGreaterThanOrEqual(2));
    for (const name of ["首帧", "尾帧"]) {
      expect(within(panel).getByText(name), `「${name}」这一格该有自己的名字`).toBeTruthy();
    }
  });

  it("不再给这两项画文件名下拉(枚举只在完整工作流的参数里出现)", async () => {
    renderStudio();
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    await waitFor(() => expect(panel.querySelector('input[type="file"]')).toBeTruthy());
    const selects = [...panel.querySelectorAll("[role=combobox]")].map((one) => one.textContent ?? "");
    expect(selects.some((text) => text.includes("49.image") || text.includes("50.image"))).toBe(false);
    expect(panel.textContent).not.toContain("49.image");
  });
});
