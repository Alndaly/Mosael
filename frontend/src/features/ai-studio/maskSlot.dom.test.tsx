/** @vitest-environment jsdom */

/**
 * 蒙版槽那一行**接上了编辑器**(ADR 0056 第二步):空槽多一格「画一张」,点它开的是蒙版编辑器。
 *
 * 这一条走的是完整那条路 —— 描述符(`form` 里的一项角色是 `mask`)→ 精简表单 → FrameSlotField 的
 * `onDrawMask` → GenerateWorkspace 里的 MaskEditor。tsc 看得出类型,看不出这条线有没有接错人。
 *
 * 编辑器里面的三件事(工具、取消、存下去的是什么)在 components/generation/MaskEditor.dom.test.tsx。
 * 这里只钉「从这一格能开到它」。
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
  //: jsdom 没有 canvas 2D(没有它就在控制台刷 "Not implemented")。编辑器拿不到上下文时只是画不出东西,
  //: 这条路要验的是"开得出来、取消得掉",给一个最小假 ctx 就够。
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement) {
    return {
      canvas: this,
      fillStyle: "",
      globalAlpha: 1,
      fillRect() {},
      clearRect() {},
      drawImage() {},
      beginPath() {},
      arc() {},
      ellipse() {},
      fill() {},
      createRadialGradient: () => ({ addColorStop() {} }),
      createImageData: (width: number, height: number) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
      getImageData: (_x: number, _y: number, width: number, height: number) => ({
        width,
        height,
        data: new Uint8ClampedArray(width * height * 4),
      }),
      putImageData() {},
    };
  } as unknown as typeof HTMLCanvasElement.prototype.getContext;
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
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
});

/** 一张局部重绘的工作流:精简表单上就两项,提示词和**蒙版**。 */
const ENGINE = {
  id: "p1:image:局部重绘.json#mask1", provider_profile_id: "p1", plugin_instance_id: "inst",
  profile_name: "演示", provider: "comfyui", kind: "image", model: "局部重绘.json#mask1",
  model_label: "局部重绘", group: "常用", capabilities_known: true, adapter_available: true, is_default: true,
  capabilities: {
    modes: [],
    parameter_keys: ["prompt", "mask"],
    prompt: "optional",
    source_limits: { mask: 1 },
    source_labels: { mask: ["要改的地方"] },
    form: {
      title: "局部重绘",
      description: "",
      items: [{ key: "prompt", label: "提示词" }, { key: "mask", label: "蒙版" }],
    },
  },
};

/**
 * 同一张工作流的「完整工作流」入口(ADR 0045):描述符**没有** `form`,右栏走通用那一栏。
 * 插件给这张图配了参考图 + 蒙版两格(一张图两用时 `graph.slots` 给的就是这两格)。
 */
const FULL_ENTRY = {
  ...ENGINE,
  id: "p1:image:局部重绘.json",
  model: "局部重绘.json",
  capabilities: {
    modes: [],
    parameter_keys: ["prompt", "reference_image", "mask"],
    prompt: "optional",
    source_limits: { reference_image: 1, mask: 1 },
    source_labels: { reference_image: ["原图"], mask: ["要改的地方"] },
  },
};

function renderStudio(engine: typeof ENGINE | typeof FULL_ENTRY = ENGINE) {
  const session = {
    id: "s1", workspace_id: "w1", title: "image", kind: "image", provider_profile_id: "p1", model: engine.model,
    origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", is_mine: true, shared: false,
    created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z",
  };
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

describe("蒙版槽:能开到编辑器", () => {
  it("蒙版那一行有「画一张」;点它开的是蒙版编辑器,取消就关掉", async () => {
    renderStudio();
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    //: 蒙版那一格多了「画一张」(上传那一条路照旧,见 FrameSlotField 的用例)。
    const draw = await within(panel).findByRole("button", { name: "maskDraw" });
    //: 上传那一格照旧,名字用模型给的槽位名(描述符的 source_labels)。
    expect(within(panel).getByRole("button", { name: "要改的地方" })).toBeTruthy();
    //: 没打开之前没有编辑器。
    expect(screen.queryByRole("dialog", { name: "maskEditorTitle" })).toBeNull();

    draw.click();

    const editor = await screen.findByRole("dialog", { name: "maskEditorTitle" });
    expect(within(editor).getByLabelText("maskCanvasLabel")).toBeTruthy();
    //: 这一组里没有原图(参考图/首帧/待编辑视频都没挂),所以没有底图 —— 但编辑器照样能用。
    expect(within(editor).getByRole("button", { name: "maskSave" }).hasAttribute("disabled")).toBe(false);

    within(editor).getByRole("button", { name: "cancel" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "maskEditorTitle" })).toBeNull());
  });

  it("完整工作流入口(没有精简表单)的通用那一栏也有蒙版那一格,能画、能开到同一个编辑器", async () => {
    renderStudio(FULL_ENTRY);
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    //: 此前通用那一栏按模型种类手列角色:图像只列参考图,描述符声明的蒙版画不出来(提交那一半却会发它)。
    expect(await within(panel).findByRole("button", { name: "原图" })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "要改的地方" })).toBeTruthy();
    within(panel).getByRole("button", { name: "maskDraw" }).click();
    expect(await screen.findByRole("dialog", { name: "maskEditorTitle" })).toBeTruthy();
  });
});
