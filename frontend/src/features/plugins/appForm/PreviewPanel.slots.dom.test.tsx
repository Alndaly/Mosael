/** @vitest-environment jsdom */

/**
 * 预览里的**普通素材槽**(「参考图」「参考视频」这类角色的那几格),和真面板里同一个角色的槽位**是同一套装法**。
 *
 * 维护者那张表(`video_minimax_h3_i2v` 的「首尾帧生成视频」,2026-10-12):预览这一栏写的是「用的人看到的就是这样」。
 * 首尾帧那一对已经收口了(见 PreviewPanel.keyframes.dom.test.tsx),而**普通素材槽那几格**当时还是自己抄的一份格子壳:
 *
 * - 少了 `w-full` / `min-w-0` / `content-center`,还把 `content-center` 换成了 **`place-items-center`** ——
 *   后者里的 `justify-items: center` 会把格子里那一行按 **max-content** 排版:名字长了省略号永远不触发、
 *   两头硬裁(真浏览器实测与理由写在 components/generation/slotTiles 的 `SLOT_TILE` 上头;面板那一侧的断言在
 *   ai-studio/FrameSlotField.dom.test.tsx)。这一格和首尾帧那一格挨着画在同一栏里,一种截法一种裁法最刺眼。
 * - 名字是**第二套链条**(「角色名 + 第几格」),而共用件与 lib/sourceFrames.slotName 那条链是
 *   「模型给的槽位名 → 角色名」—— 两处的注释都写着「面板与预览走同一条链」。
 *
 * 所以这里钉住:两边那一格**逐项对得上** —— 壳的类、名字那一行、列宽,以及 `place-items-center` 的**缺席**。
 *
 * 怎么比:面板那一侧是**真的**渲染 `AiStudio`(和 PreviewPanel.keyframes.dom.test.tsx 同一套 fetch 替身),
 * 两侧都由共用的那几样画出来(`SLOT_TILE` / `SlotTileText` / `slotColumns` / `slotName`),用例照 DOM 逐项比。
 * jsdom 没有排版、量不了宽,所以按**类与 DOM 结构**比(同 design/truncateNeedsShrinkableBox 的做法)。
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

/** 面板那一侧要的那份引擎描述符 —— 用例只用到这几个字段。 */
interface EngineFixture {
  id: string;
  model: string;
  kind: string;
  capabilities: Record<string, unknown>;
  [key: string]: unknown;
}

/**
 * 一张有两个读图节点的工作流(ComfyUI 里那两个节点叫「人物」「背景」,见 ADR 0038 §4):两个槽位都属于
 * `reference_image`,插件给它们报了名字(`source_labels`)。表上只留了第一格 —— 第二格不在表上,预览就不画它
 * (这是这一栏自己的规矩)。
 *
 * 面板此刻画的是**下一格要填的**:空槽只有一个(填满一格才会长出下一格),所以两边这时候都是一格,能整行比。
 */
const REFERENCE_ENGINE: EngineFixture = {
  id: "p1:image:upscale.json#k7m2", provider_profile_id: "p1", plugin_instance_id: "inst",
  profile_name: "演示", provider: "comfyui", kind: "image", model: "upscale.json#k7m2",
  model_label: "参考图放大", group: "upscale", capabilities_known: true, adapter_available: true, is_default: true,
  capabilities: {
    modes: ["image-to-image"],
    parameter_keys: ["reference_image", "13.strength_model"],
    prompt: "none",
    source_limits: { reference_image: 2 },
    source_labels: { reference_image: ["人物", "背景"] },
    source_keys: { reference_image: ["10.image"] },
    requires_source: [["reference_image"]],
    parameter_schema: { "13.strength_model": { type: "number", title: "放大倍数", default: 2 } },
    form: {
      title: "参考图放大",
      description: "",
      items: [
        { key: "10.image", label: "人物" },
        { key: "13.strength_model", label: "放大倍数" },
      ],
    },
  },
};

/** 那两个读图节点(节点的名字就是槽位名:`node_title` 就是插件报上来的 `source_labels` 的那一条)。 */
function imageData(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return {
    path: "upscale.json",
    modified: 1,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "人物", node_title: "人物", node_label: "加载图像", class_type: "LoadImage", spec: null },
      { ...base, key: "11.image", node: "11", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "背景", node_title: "背景", node_label: "加载图像", class_type: "LoadImage", spec: null },
      { ...base, key: "13.strength_model", node: "13", input: "strength_model", kind: "number", title: "放大倍数",
        node_label: "放大", class_type: "Upscale", spec: { type: "number", default: 2 } },
    ],
    outputs: [],
    app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  } as WorkflowApp;
}

/** 一张表单的草稿:作者排的顺序(键就是数据里的键)。 */
function draft(keys: string[]): FormDraft {
  return {
    id: "", key: "new-1", title: "参考图放大", description: "", model: "", tool: "",
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

/** 面板那一侧:**真的**把 AI Studio 画出来(和 PreviewPanel.keyframes.dom.test.tsx 同一套替身)。 */
async function renderPanel(engine: EngineFixture): Promise<HTMLElement> {
  const session = {
    id: "s1", workspace_id: "w1", title: "image", kind: "image", provider_profile_id: "p1", model: engine.model,
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
  //: 这一格要等描述符到位才画得出来(那一格的读屏名字就是它此时要下一格填的那个槽位名)。
  await within(panel).findByRole("button", { name: "人物" });
  return panel as HTMLElement;
}

/**
 * 面板那一侧:一个角色的素材行 —— 那一格是 FrameSlotField 画出来的按钮,行是它外面那一格网格。
 * (面板这一侧没有专门的 DOM 抓手:这一格自己就是抓手,`SLOT_TILE` 那一段类名是它和预览共用的那一份。)
 */
function panelRow(panel: HTMLElement, name: string): HTMLElement {
  return within(panel).getByRole("button", { name }).parentElement as HTMLElement;
}

/** 预览那一侧:同一个角色的素材行 —— 抓手是表上那一项自己的 `data-app-field`(和 PreviewPanel.dom.test.tsx 同一个)。 */
function previewRow(preview: HTMLElement, key: string): HTMLElement {
  return preview.querySelector(`[data-app-field="${key}"] ul`) as HTMLElement;
}

/** 一行里真正看得见的那几格:面板那一格是按钮(旁边还挂着一个 `sr-only` 的选文件框,不算格子),预览那一格是 `<li>`。 */
function tilesOf(row: HTMLElement): HTMLElement[] {
  return (Array.from(row.children) as HTMLElement[]).filter((one) => one.tagName === "BUTTON" || one.tagName === "LI");
}

/** 格子上那几件事:固定高度、圆角、虚线、铺满、能收缩、竖着居中(写法见 components/generation/slotTiles.SLOT_TILE)。 */
function tileShell(tile: HTMLElement): string[] {
  const shared = ["grid", "h-[68px]", "w-full", "min-w-0", "content-center", "overflow-hidden",
                  "rounded-lg", "border", "border-border", "border-dashed", "bg-muted/40"];
  return tile.className.split(/\s+/).filter((one) => shared.includes(one)).sort();
}

/**
 * 一个角色的素材行在 DOM 里的样子 —— 面板与预览**照这个对象逐项比**。
 *
 * 比的是三件事:列宽(两边都由 `sourceFrames.slotColumns` 说了算:一份铺满整行、最多三份)、每一格的壳
 * (`SLOT_TILE` 那一段),以及名字那一行(`SlotTileText` 的外层 + 里面 `Truncate` 那一格)。
 * `placeItems` 单列出来:这一格**不许**把里面的行按内容宽排版(`place-items-center` 的那个坑)。
 */
function rowShape(row: HTMLElement) {
  return {
    columns: row.style.gridTemplateColumns,
    tiles: tilesOf(row).map((tile) => ({
      shell: tileShell(tile),
      placeItems: tile.className.includes("place-items-center"),
      nameRow: (tile.querySelector("span") as HTMLElement).className,
      //: 名字那一格:面板那一行里前面还有个加号,预览那一行没有 —— 这里比的就是名字那一格自己。
      nameCell: (tile.querySelector("span.truncate") as HTMLElement).className,
      text: (tile.textContent ?? "").trim(),
    })),
  };
}

describe("预览的素材槽与真面板:同一格,逐项对上", () => {
  it("两边那一格是同一格:壳、名字那一行、列宽都一样,而且不按内容宽排版", async () => {
    const panel = await renderPanel(REFERENCE_ENGINE);
    //: 表上只留了第一个槽位(第二个节点没进表)→ 两边此刻都只有一格,能整行比。
    const preview = renderPreview(imageData(), ["10.image"]);
    expect(rowShape(previewRow(preview, "reference_image"))).toEqual(rowShape(panelRow(panel, "人物")));
    expect(rowShape(panelRow(panel, "人物"))).toEqual({
      columns: "repeat(1, minmax(0, 1fr))",
      tiles: [{
        //: 共用的那一份壳(见 components/generation/slotTiles.SLOT_TILE):此前预览那一份少了 w-full / min-w-0 / content-center
        shell: ["bg-muted/40", "border", "border-border", "border-dashed", "content-center", "grid", "h-[68px]",
                "min-w-0", "overflow-hidden", "rounded-lg", "w-full"].sort(),
        //: 那一格**不许**把里面的行按内容宽排版:省略号会永远不触发、两头硬裁(见 SLOT_TILE 上头那段实测)
        placeItems: false,
        //: 名字那一行是共用的 SlotTileText:自己居中(justify-center),而且能收缩(min-w-0)
        nameRow: "flex min-w-0 items-center justify-center gap-1 px-1.5",
        nameCell: "block min-w-0 truncate",
        text: "人物",
      }],
    });
  });

  it("两处读的是同一份 source_labels、同一个顺序:第 i 格写的字就是模型给的第 i 个槽位名", async () => {
    const panel = await renderPanel(REFERENCE_ENGINE);
    //: 表上两个槽位都在 → 预览把这一行整个铺出来:两格,名字按模型给的顺序(不是「参考图 1」「参考图 2」)
    const preview = renderPreview(imageData(), ["10.image", "11.image"]);
    expect(rowShape(previewRow(preview, "reference_image")).tiles.map((tile) => tile.text)).toEqual(["人物", "背景"]);
    expect(rowShape(previewRow(preview, "reference_image")).columns).toBe("repeat(2, minmax(0, 1fr))");
    //: 面板此刻画的是**下一格要填的**(空槽只有一个):同一个链、同一份名字里的第一个
    expect(rowShape(panelRow(panel, "人物")).tiles.map((tile) => tile.text)).toEqual(["人物"]);
    //: 同一个角色、同一份来源 → 壳与名字那一行两处一样(面板这一格就是预览那一行里的第一格)
    const previewTiles = rowShape(previewRow(preview, "reference_image")).tiles;
    expect(previewTiles[0]).toEqual(rowShape(panelRow(panel, "人物")).tiles[0]);
  });

  it("表上没有的格子不画:草稿里只有一个槽位,预览就只有一格(第二个节点不画)", () => {
    const preview = renderPreview(imageData(), ["10.image"]);
    expect(tilesOf(previewRow(preview, "reference_image"))).toHaveLength(1);
    expect(rowShape(previewRow(preview, "reference_image")).tiles.map((tile) => tile.text)).toEqual(["人物"]);
  });
});
