/** @vitest-environment jsdom */

/**
 * 右侧预览按**作者排的顺序**画 —— 和生成面板的「引擎参数」同一份判据(见 lib/appFormFields)。
 *
 * 维护者报的 bug 很具体:中间那一列把「参考图」拖到「放大倍数」下面,预览里什么都看不出变化。原因是预览自己按
 * 分好的类摆(提示词 → 反向提示词 → 素材槽 → 尺寸 → 张数 → 种子 → 参数),参数永远排在素材后面,跨类拖动对
 * 它没有影响 —— 而用的人看到的偏偏是面板那一份。这里钉住:草稿怎么排,预览就怎么摆。
 *
 * 断言看的是 `data-app-preview` 容器里每一项的 `data-app-field`(那一项在描述符里的键:参数是
 * `<节点>.<输入名>`,素材槽是它的角色)以及它们在人眼里的先后。
 */

import { render } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ getWorkflowApp: vi.fn(), annotateWorkflow: vi.fn(), getFormUsages: vi.fn() }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { WorkflowApp } from "@/api/client";
import { PreviewPanel } from "@/features/plugins/appForm/PreviewPanel";
import type { FormDraft } from "@/features/plugins/workflowAppForm";

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

/** 这张工作流:一个读图的槽位(参考图)和一个数字参数(放大倍数)。名字是「一句或一张语言表」,按界面语言挑。 */
function data(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true };
  return {
    path: "放大.json",
    modified: 1,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image",
        title: { zh: "参考图 · 人物", en: "Reference · Person" }, node_title: "人物",
        node_label: { zh: "加载图像", en: "LoadImage" }, class_type: "LoadImage", spec: null },
      { ...base, key: "13.strength_model", node: "13", input: "strength_model", kind: "number",
        title: { zh: "放大倍数", en: "Upscale factor" },
        node_label: { zh: "放大", en: "Upscale" }, class_type: "Upscale", spec: { type: "number", default: 2 } },
    ],
    outputs: [],
    app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  } as WorkflowApp;
}

/** 一张表单的草稿:作者起的名字、作者排的顺序。`named: false` 是作者没起名字的那一种(名字用插件交回的)。 */
function draft(keys: string[], named = true): FormDraft {
  return {
    id: "", key: "new-1", title: "放大", description: "", model: "", tool: "",
    items: keys.map((key) => {
      const [node, input] = key.split(".");
      const label = named && key === "13.strength_model" ? "放大倍数" : "";
      return { key, node, input, label, main: false, choices: null, problem: "" };
    }),
  };
}

/** 渲染一份预览,`named: false` 时那一格的名字来自插件交回的那张语言表(见 lib/pickLabel)。 */
function previewOf(keys: string[], named = true) {
  render(<PreviewPanel instanceId="i1" data={data()} draft={draft(keys, named)} />);
  const container = document.querySelector("[data-app-preview]") as HTMLElement;
  const order = () => Array.from(container.querySelectorAll("[data-app-field]"))
    .map((one) => one.getAttribute("data-app-field"));
  const at = (text: string) => (container.textContent ?? "").indexOf(text);
  return { container, order, at };
}

describe("右侧预览:顺序就是表上的顺序", () => {
  it("参数在前、参考图在后:预览也这么摆(此前素材槽永远排在参数前面)", () => {
    const preview = previewOf(["13.strength_model", "10.image"]);
    expect(preview.order()).toEqual(["13.strength_model", "reference_image"]);
    //: 人眼看到的先后也一样:参数那一格(名字来自表单)、素材那一格(角色名 + 槽位名)
    expect(preview.at("放大倍数")).toBeGreaterThanOrEqual(0);
    expect(preview.at("genReferenceImage")).toBeGreaterThan(preview.at("放大倍数"));
    expect(preview.container.textContent).toContain("人物");
  });

  it("反过来排(参考图在前):预览跟着换回去", () => {
    const preview = previewOf(["10.image", "13.strength_model"]);
    expect(preview.order()).toEqual(["reference_image", "13.strength_model"]);
    expect(preview.at("放大倍数")).toBeGreaterThan(preview.at("genReferenceImage"));
  });

  it("表上没有的格子不画:草稿里没有那个参数就没有那一格", () => {
    const preview = previewOf(["10.image"]);
    expect(preview.order()).toEqual(["reference_image"]);
    expect(preview.at("放大倍数")).toBe(-1);
  });

  it("作者没起名字的那一格:用插件交回的名字(表里按界面语言挑一句,见 lib/pickLabel)", () => {
    const preview = previewOf(["13.strength_model"], false);
    //: 插件交回的是 `{zh: "放大倍数", en: "Upscale factor"}` —— 界面是中文,挑的是中文那一份
    expect(preview.at("放大倍数")).toBeGreaterThanOrEqual(0);
    expect(preview.at("Upscale factor")).toBe(-1);
  });
});
