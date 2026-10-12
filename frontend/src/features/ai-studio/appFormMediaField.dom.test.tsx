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

/**
 * 维护者那张表(2026-10-12):`video_minimax_h3_i2v` 的「首尾帧生成视频」—— 表上四项,首帧、尾帧是**两条**。
 * 角色、槽位名、项的名字都照插件在那台 ComfyUI(8120)上报的抄。
 */
const H3_ENGINE = {
  ...ENGINE,
  id: "p1:video:video_minimax_h3_i2v.json#k0a1nq",
  model: "video_minimax_h3_i2v.json#k0a1nq",
  model_label: "首尾帧生成视频",
  group: "video_minimax_h3_i2v",
  capabilities: {
    modes: ["keyframes-to-video"],
    parameter_keys: ["first_frame", "last_frame", "115.aspect_ratio", "115.megapixels"],
    prompt: "none",
    source_limits: { first_frame: 1, last_frame: 1 },
    source_labels: { first_frame: ["Optional Load Image #127"], last_frame: ["Optional Load Image #128"] },
    source_keys: { first_frame: ["127.image"], last_frame: ["128.image"] },
    requires_source: [["first_frame"]],
    parameter_schema: {
      "115.aspect_ratio": { type: "string", title: "Resolution Selector · Aspect ratio", default: "2:3 (Portrait Photo)",
                            enum: ["1:1 (Square)", "2:3 (Portrait Photo)"] },
      "115.megapixels": { type: "number", title: "像素量(百万)", default: 0.6 },
    },
    form: {
      title: "首尾帧生成视频",
      description: "",
      items: [
        { key: "first_frame", label: "首帧 · Optional Load Image #127" },
        { key: "last_frame", label: "尾帧 · Optional Load Image #128" },
        { key: "115.aspect_ratio", label: "Resolution Selector · Aspect ratio" },
        { key: "115.megapixels", label: "像素量(百万)" },
      ],
    },
  },
};

function renderStudio(engine: typeof ENGINE = ENGINE) {
  const session = {
    id: "s1", workspace_id: "w1", title: "video", kind: "video", provider_profile_id: "p1", model: engine.model,
    origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", is_mine: true, shared: false,
    created_at: "2026-10-11T00:00:00Z", updated_at: "2026-10-11T00:00:00Z",
  };
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/options")) return json([engine]);
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

  /**
   * 表上四项、其中两条是素材的那张表(维护者截图):首帧、尾帧在表上是**两条**,在面板里仍然是**一个控件、两格** ——
   * 不是把这个控件画两遍(四格)。两格各自带着自己的槽位名,谁也没被吞掉。
   */
  it("表上首帧、尾帧两条(还有两个参数):首尾帧仍然是一个控件里的两格", async () => {
    renderStudio(H3_ENGINE);
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    await waitFor(() => expect(panel.querySelectorAll('input[type="file"]').length).toBe(2));
    //: 一个「首尾帧」控件,不是两个
    expect(within(panel).getAllByText("genKeyframes")).toHaveLength(1);
    //: 两格各带自己的名字(描述符的 source_labels),一条都没少
    for (const name of ["Optional Load Image #127", "Optional Load Image #128"]) {
      expect(within(panel).getByText(name), `「${name}」这一格该在`).toBeTruthy();
    }
    //: 表上另外两个参数照旧画出来(这两条是参数,不是素材)
    expect(within(panel).getByText("Resolution Selector · Aspect ratio")).toBeTruthy();
    expect(within(panel).getByText("像素量(百万)")).toBeTruthy();
  });
});
