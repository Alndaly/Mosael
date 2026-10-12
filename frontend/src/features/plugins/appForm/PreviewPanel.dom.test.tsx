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

/** 这张工作流:一个读图的槽位(参考图)和一个数字参数(放大倍数)。 */
function data(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return {
    path: "放大.json",
    modified: 1,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "参考图 · 人物", node_title: "人物", node_label: "加载图像", class_type: "LoadImage", spec: null },
      { ...base, key: "13.strength_model", node: "13", input: "strength_model", kind: "number", title: "放大倍数",
        node_label: "放大", class_type: "Upscale", spec: { type: "number", default: 2 } },
    ],
    outputs: [],
    app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  } as WorkflowApp;
}

/** 一张表单的草稿:作者起的名字、作者排的顺序。 */
function draft(keys: string[]): FormDraft {
  return {
    id: "", key: "new-1", title: "放大", description: "", model: "", tool: "",
    items: keys.map((key) => {
      const [node, input] = key.split(".");
      return { key, node, input, label: key === "13.strength_model" ? "放大倍数" : "", main: false, choices: null, problem: "" };
    }),
  };
}

/**
 * 维护者那张表(`video_minimax_h3_i2v` 的「首尾帧生成视频」,2026-10-12 的截图):两条读图槽位 + 两个参数。
 * 两条素材项的角色和名字都照插件在那台 ComfyUI(8120)上报的抄:`first_frame` → `127.image`(Optional Load Image #127)、
 * `last_frame` → `128.image`(Optional Load Image #128)。
 */
function videoData(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return {
    path: "video_minimax_h3_i2v.json",
    modified: 1,
    kind: "video",
    editable: true,
    items: [
      { ...base, key: "127.image", node: "127", input: "image", kind: "media", role: "first_frame", media: "image",
        title: "首帧 · Optional Load Image #127", node_label: "Optional Load Image", class_type: "Optional Load Image",
        spec: null },
      { ...base, key: "128.image", node: "128", input: "image", kind: "media", role: "last_frame", media: "image",
        title: "尾帧 · Optional Load Image #128", node_label: "Optional Load Image", class_type: "Optional Load Image",
        spec: null },
      { ...base, key: "115.aspect_ratio", node: "115", input: "aspect_ratio", kind: "choice",
        title: "Resolution Selector · Aspect ratio", node_label: "ResolutionSelector", class_type: "ResolutionSelector",
        spec: { type: "string", default: "2:3 (Portrait Photo)", enum: ["1:1 (Square)", "2:3 (Portrait Photo)"] } },
    ],
    outputs: [],
    app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  } as WorkflowApp;
}

function previewOf(keys: string[], app: WorkflowApp = data()) {
  render(<PreviewPanel instanceId="i1" data={app} draft={draft(keys)} />);
  const container = document.querySelector("[data-app-preview]") as HTMLElement;
  const order = () => Array.from(container.querySelectorAll("[data-app-field]"))
    .map((one) => one.getAttribute("data-app-field"));
  const at = (text: string) => (container.textContent ?? "").indexOf(text);
  /** 某一格里的素材框(虚线格):预览画了几个框,这里就数出几个。 */
  const boxes = (key: string) =>
    Array.from(container.querySelectorAll(`[data-app-field="${key}"] li`)).map((one) => one.textContent ?? "");
  return { container, order, at, boxes };
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
});

describe("右侧预览:视频的首帧、尾帧是两格,两格都要画", () => {
  it("表上首帧、尾帧两条都在 → 预览里两个素材框都在,各自带着自己的名字(此前只剩首帧那一格)", () => {
    const preview = previewOf(["127.image", "128.image", "115.aspect_ratio"], videoData());
    //: 两格都在,而且就是表上的位置(尾帧那一项此前被「首尾帧是一个控件」那条规则吞掉)
    expect(preview.order()).toEqual(["first_frame", "last_frame", "115.aspect_ratio"]);
    //: 首帧那一格:一个框,名字是它自己的槽位名
    expect(preview.boxes("first_frame")).toEqual(["Optional Load Image #127"]);
    //: 尾帧那一格:也在,名字也是它自己的 —— 用的人看到两格,预览里就是两格
    expect(preview.boxes("last_frame")).toEqual(["Optional Load Image #128"]);
  });

  it("两条素材项的名字由各自的项决定,不会两格写成同一个", () => {
    const preview = previewOf(["127.image", "128.image"], videoData());
    const shown = [...preview.boxes("first_frame"), ...preview.boxes("last_frame")];
    expect(shown).toHaveLength(2);
    expect(new Set(shown).size).toBe(2);
  });
});
