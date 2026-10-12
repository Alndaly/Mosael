/** @vitest-environment jsdom */

/**
 * 预览里的首帧、尾帧,和真面板里的是**同一组东西**。
 *
 * 维护者 2026-10-12 的两张截图:同一张表单(视频工作流 `video_minimax_h3_i2v` 的「首尾帧生成视频」),AI Studio 右侧的
 * 「引擎参数」里首帧、尾帧是**一个控件里的两格** —— 一行标题「首尾帧」+ 说明一句 + 左右两格并排 + 中间一个对调箭头;
 * 表单编辑器的「预览」里,同一对东西却是**两个各自独立的竖框**(各自标「首帧」「尾帧」,里面是节点名),既不并排、也没有箭头。
 * 而预览那一栏自己的说明是「用的人看到的就是这样」—— 所以这里钉住:两边画的是同一组,而且逐项对得上。
 *
 * **怎么比**才不是"看起来差不多":两边都由同一个壳画出来(components/generation/slotTiles.KeyframePairFrame),用例照那个壳的
 * 抓手(`data-keyframe-pair` / `data-keyframe-row`)把两边的结构拆成一个对象逐项比 —— 面板那一侧是**真的**渲染
 * `AiStudio`(和 appFormMediaField.dom.test.tsx 同一套 fetch 替身),不是拿控件单独摆一个。
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { WorkflowApp } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { AiStudio } from "@/features/ai-studio/AiStudio";
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

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
  localStorage.setItem("mosael:tab:ai-studio-create-filter", "all");
});

/** 面板那一侧要的那份引擎描述符 —— 用例只用到这几个字段,值照插件在那台 ComfyUI(8120)上报的抄。 */
interface EngineFixture {
  id: string;
  model: string;
  kind: string;
  capabilities: Record<string, unknown>;
  [key: string]: unknown;
}

/**
 * 真面板拿到的引擎描述符:维护者那张表(2026-10-12,插件在那台 ComfyUI 8120 上报的照抄)。
 * 表上四项,首帧、尾帧是**两条**,而它们在一个控件里画成两格。
 */
const H3_ENGINE: EngineFixture = {
  id: "p1:video:video_minimax_h3_i2v.json#k0a1nq", provider_profile_id: "p1", plugin_instance_id: "inst",
  profile_name: "演示", provider: "comfyui", kind: "video", model: "video_minimax_h3_i2v.json#k0a1nq",
  model_label: "首尾帧生成视频", group: "video_minimax_h3_i2v", capabilities_known: true, adapter_available: true, is_default: true,
  capabilities: {
    modes: ["keyframes-to-video"],
    parameter_keys: ["first_frame", "last_frame", "115.aspect_ratio"],
    prompt: "none",
    source_limits: { first_frame: 1, last_frame: 1 },
    source_labels: { first_frame: ["Optional Load Image #127"], last_frame: ["Optional Load Image #128"] },
    source_keys: { first_frame: ["127.image"], last_frame: ["128.image"] },
    requires_source: [["first_frame"]],
    parameter_schema: {
      "115.aspect_ratio": { type: "string", title: "Resolution Selector · Aspect ratio", default: "2:3 (Portrait Photo)",
                            enum: ["1:1 (Square)", "2:3 (Portrait Photo)"] },
    },
    form: {
      title: "首尾帧生成视频",
      description: "",
      items: [
        { key: "first_frame", label: "首帧 · Optional Load Image #127" },
        { key: "last_frame", label: "尾帧 · Optional Load Image #128" },
        { key: "115.aspect_ratio", label: "Resolution Selector · Aspect ratio" },
      ],
    },
  },
};

/** 只认首帧的视频工作流:面板那一侧的 `showLast` 就是为它存在的(不画第二格、不画箭头)。 */
const FIRST_ONLY_ENGINE: EngineFixture = {
  ...H3_ENGINE,
  id: "p1:video:img2video.json#f1r5t",
  model: "img2video.json#f1r5t",
  model_label: "首帧生成视频",
  group: "img2video",
  capabilities: {
    modes: ["keyframes-to-video"],
    parameter_keys: ["first_frame"],
    prompt: "none",
    source_limits: { first_frame: 1 },
    source_labels: { first_frame: ["Optional Load Image #127"] },
    source_keys: { first_frame: ["127.image"] },
    requires_source: [["first_frame"]],
    form: { title: "首帧生成视频", description: "", items: [{ key: "first_frame", label: "首帧 · Optional Load Image #127" }] },
  },
};

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

/** 同一张表,但**工作流只有首帧那个槽位** —— 尾帧那一项连数据里都没有。 */
function firstOnlyData(): WorkflowApp {
  const data = videoData();
  return { ...data, path: "img2video.json", items: (data.items ?? []).filter((one) => one.role !== "last_frame") };
}

/** 一张表单的草稿:作者排的顺序(键就是数据里的键)。 */
function draft(keys: string[]): FormDraft {
  return {
    id: "", key: "new-1", title: "首尾帧生成视频", description: "", model: "", tool: "",
    items: keys.map((key) => {
      const [node, input] = key.split(".");
      return { key, node, input, label: "", main: false, choices: null, problem: "" };
    }),
  };
}

/** 预览那一侧:右侧那一栏就是它(`data-app-zone=preview`)。 */
function renderPreview(app: WorkflowApp, keys: string[]): HTMLElement {
  const { container } = render(<PreviewPanel instanceId="i1" data={app} draft={draft(keys)} />);
  return container.querySelector("[data-app-zone='preview']") as HTMLElement;
}

/** 面板那一侧:**真的**把 AI Studio 画出来(和 appFormMediaField.dom.test.tsx 同一套替身)。 */
async function renderPanel(engine: EngineFixture): Promise<HTMLElement> {
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
  const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
  await waitFor(() => expect(panel.querySelector("[data-keyframe-pair]")).toBeTruthy());
  return panel as HTMLElement;
}

/**
 * 一组首尾帧在 DOM 里的样子 —— 面板与预览**照这个对象逐项比**。
 *
 * 抓手全来自那个共用的壳:组是 `data-keyframe-pair`(值是 `both` / `first`),并排那一行是 `data-keyframe-row`,
 * 一行里的三格是它的孩子:左边那一格、中间的箭头、右边那一格。格子里的字就是格子的 `textContent`。
 */
function pairShape(root: ParentNode) {
  const group = root.querySelector("[data-keyframe-pair]") as HTMLElement | null;
  const row = root.querySelector("[data-keyframe-row]") as HTMLElement | null;
  //: 一行里真正看得见的那几格:面板那一格还带着一个 `sr-only` 的选文件框(绝对定位、不占格子),
  //: 它不是控件的一部分(预览里也不可能有),比结构时不算进去。
  const cells = row ? (Array.from(row.children) as HTMLElement[]).filter((one) => one.tagName !== "INPUT") : [];
  const arrow = row ? (row.querySelector('[aria-label="genSwapKeyframes"]') as HTMLButtonElement | null) : null;
  return {
    groups: root.querySelectorAll("[data-keyframe-pair]").length,
    kind: group?.getAttribute("data-keyframe-pair") ?? null,
    title: group?.firstElementChild?.textContent ?? null,
    hint: group?.children[1]?.textContent ?? null,
    rows: root.querySelectorAll("[data-keyframe-row]").length,
    cells: cells.map((one) => (one.textContent ?? "").trim()),
    arrow: arrow?.getAttribute("aria-label") ?? null,
    arrowMiddle: arrow ? cells.findIndex((one) => one.contains(arrow)) === 1 : false,
    arrowDisabled: arrow ? arrow.disabled : null,
  };
}

/** 一行里第一格**真正那一格**(面板是按钮本身,预览那一格里还套着一层 `<ul><li>`)。 */
function firstTile(root: ParentNode): HTMLElement {
  const row = root.querySelector("[data-keyframe-row]") as HTMLElement;
  const cell = (Array.from(row.children) as HTMLElement[]).find((one) => one.tagName !== "INPUT") as HTMLElement;
  return (cell.matches("button, li") ? cell : cell.querySelector("li, button")) as HTMLElement;
}

/** 两边格子外壳上那几件事:固定高度、圆角、虚线、内容居中(写法见 components/generation/slotTiles.SLOT_TILE)。 */
function tileShell(element: HTMLElement): string[] {
  const shared = ["grid", "h-[68px]", "w-full", "min-w-0", "content-center", "overflow-hidden",
                  "rounded-lg", "border", "border-border", "border-dashed", "bg-muted/40"];
  return element.className.split(/\s+/).filter((one) => shared.includes(one)).sort();
}

describe("预览:首帧、尾帧是一组(维护者那张截图)", () => {
  it("表上两格都在 → **一组**:左右并排两格、中间一个对调箭头;不是两个各自独立的框", () => {
    const preview = renderPreview(videoData(), ["127.image", "128.image", "115.aspect_ratio"]);
    expect(pairShape(preview)).toEqual({
      groups: 1,
      kind: "both",
      title: "genKeyframes",
      hint: "genLastFrameHint",
      rows: 1,
      cells: ["Optional Load Image #127", "", "Optional Load Image #128"],
      arrow: "genSwapKeyframes",
      arrowMiddle: true,
      arrowDisabled: true,
    });
    //: 并排靠的是**面板那一份列宽**(两格 + 中间 28px 给箭头),不是预览自己定的一套
    const row = preview.querySelector("[data-keyframe-row]") as HTMLElement;
    expect(row.className).toContain("grid-cols-[minmax(0,1fr)_28px_minmax(0,1fr)]");
    //: 「不是两个各自独立的框」:整个预览里只有一个「首尾帧」标题,没有各自那一份角色标题(此前每个框头上一个)
    expect(within(preview).getByText("genKeyframes")).toBeTruthy();
    expect(within(preview).queryByText("genFirstFrame")).toBeNull();
    expect(within(preview).queryByText("genLastFrame")).toBeNull();
    //: 两格在树上是**同一个**并排行的孩子(此前各在自己的 div 里)
    const tiles = Array.from(preview.querySelectorAll("[data-app-field]"));
    expect(tiles.map((one) => one.getAttribute("data-app-field"))).toEqual(["first_frame", "last_frame", "115.aspect_ratio"]);
    for (const tile of tiles.slice(0, 2)) expect(tile.parentElement).toBe(row);
  });

  it("单帧(这张工作流只认首帧)→ 照面板那一支只画一格,不画箭头", () => {
    const preview = renderPreview(firstOnlyData(), ["127.image"]);
    expect(pairShape(preview)).toEqual({
      groups: 1,
      kind: "first",
      title: "genFirstFrame",
      hint: "genKeyframeHint",
      rows: 0,
      cells: [],
      arrow: null,
      arrowMiddle: false,
      arrowDisabled: null,
    });
    //: 那一格还在,名字照旧(描述符的 source_labels)
    expect(within(preview).getByText("Optional Load Image #127")).toBeTruthy();
    expect(within(preview).queryByRole("button", { name: "genSwapKeyframes" })).toBeNull();
  });

  it("不是首尾帧的项照旧一格一格画:参考图那一格不套这一组", () => {
    const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                   common: true, exposable: true, unexposable_reason: "" };
    const data = {
      ...videoData(),
      kind: "image",
      items: [
        { ...base, key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image",
          title: "参考图 · 人物", node_title: "人物", node_label: "加载图像", class_type: "LoadImage", spec: null },
      ],
    } as WorkflowApp;
    const preview = renderPreview(data, ["10.image"]);
    expect(preview.querySelectorAll("[data-keyframe-pair]").length).toBe(0);
    expect(within(preview).getByText("genReferenceImage")).toBeTruthy();
    expect(within(preview).getByText("人物")).toBeTruthy();
  });
});

describe("预览与真面板:同一组东西,逐项对上", () => {
  it("表上首尾帧两条都在:两边都是一组、一样的标题说明、一样的两格与名字、一样的箭头", async () => {
    const panel = await renderPanel(H3_ENGINE);
    const preview = renderPreview(videoData(), ["127.image", "128.image", "115.aspect_ratio"]);
    expect(pairShape(preview)).toEqual(pairShape(panel));
    expect(pairShape(panel)).toEqual({
      groups: 1,
      kind: "both",
      title: "genKeyframes",
      hint: "genLastFrameHint",
      rows: 1,
      cells: ["Optional Load Image #127", "", "Optional Load Image #128"],
      arrow: "genSwapKeyframes",
      arrowMiddle: true,
      arrowDisabled: true,
    });
  });

  it("单帧那张工作流:两边都只画一格、都不画箭头", async () => {
    const panel = await renderPanel(FIRST_ONLY_ENGINE);
    const preview = renderPreview(firstOnlyData(), ["127.image"]);
    expect(pairShape(preview)).toEqual(pairShape(panel));
    expect(pairShape(panel).kind).toBe("first");
  });

  it("两边的格子是**同一个壳**:同样的高度/圆角/虚线,名字长了同样出省略号", async () => {
    const panel = await renderPanel(H3_ENGINE);
    const preview = renderPreview(videoData(), ["127.image", "128.image", "115.aspect_ratio"]);
    expect(tileShell(firstTile(preview))).toEqual(tileShell(firstTile(panel)));
    //: 名字那一行也是同一份写法(见 components/generation/slotTiles.SlotTileText):居中那一行 + 截断那一格
    const nameRow = (root: ParentNode) => {
      const row = firstTile(root).querySelector("span") as HTMLElement;
      //: 面板那一格里这一行还有个加号(`shrink-0` 那个 span),预览那一格没有 —— 这里比的是名字那一格
      return { row: row.className, text: (row.querySelector("span.truncate") as HTMLElement).className };
    };
    expect(nameRow(preview)).toEqual(nameRow(panel));
  });
});
