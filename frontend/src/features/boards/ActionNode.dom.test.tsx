/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

/**
 * 工具格在画布上的样子,和它交回的结构化数据落成的便签。
 *
 * 工具格自己不放产出:画的是「这是什么工具、从哪来、现在怎样」—— 它自己的图标、空着时一份摘要
 * (吃什么、关键设置、产出什么),在跑时扫光 + 停止按钮,跑挂了写原因,清单里查不到时说它用不了。
 */

vi.mock("@xyflow/react", () => ({
  Handle: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) => selector({ transform: [0, 0, 1] }),
}));
//: 「接{kinds}」那几条给出真的模板,看得出几种格子是怎么连成一句的;别的 key 原样返回。
const TEMPLATES: Record<string, string> = { boardToolConnect: "接{kinds}", boardToolKindsOr: "或", listSeparator: "、" };
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => TEMPLATES[key] ?? key }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getJob: vi.fn(async () => ({ id: "job-1", progress: 0.4 })),
}));

import { Image as ImageIcon, Languages } from "lucide-react";

import { BOARD_NODE_TYPES, type BoardToolFace } from "./boardNodes";

afterEach(cleanup);

const TOOL: BoardToolFace = {
  label: "去背景",
  description: "把**主体**抠出来",
  plugin: "我的抠图",
  icon: ImageIcon,
  inputs: [{ key: "image", label: "图片", kinds: ["image"] }],
  settings: [],
  products: [{ label: "抠好的图", text: false }],
};

const TRANSLATE: BoardToolFace = {
  label: "翻译",
  description: "把便签或文档里的文字翻成另一种语言",
  plugin: "",
  icon: Languages,
  inputs: [{ key: "text", label: "文本", kinds: ["note", "document"] }],
  settings: [{ key: "target_lang", label: "目标语言", value: null }],
  products: [{ label: "文本", text: true }],
};

/** lucide 的图标画成 `<svg class="lucide lucide-<名字>">` —— 按类名认是哪一颗。 */
const iconsIn = (selector: string) =>
  [...document.querySelectorAll(`${selector} svg`)].map((svg) => svg.getAttribute("class") ?? "");

function renderAction(item: BoardItem, extra: { tool?: BoardToolFace | null; onStop?: (id: string) => void } = {}) {
  const Node = BOARD_NODE_TYPES.action;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props = {
    id: item.id,
    data: { item, onText: vi.fn(), onAspect: vi.fn(), ...extra },
    selected: false,
  } as unknown as React.ComponentProps<typeof Node>;
  return render(
    <QueryClientProvider client={client}>
      <Node {...props} />
    </QueryClientProvider>,
  );
}

const action = (run?: BoardItem["run"]): BoardItem => ({
  id: "a1", kind: "action", x: 0, y: 0, form: { producer: "node:plugin.cut.out" }, ...(run ? { run } : {}),
});

describe("工具格", () => {
  it("没起名时用工具的名字;插件工具在说明前点名插件(和「添加」菜单同一个写法);说明按行内 Markdown 渲染", () => {
    renderAction(action(), { tool: TOOL });
    expect(screen.getAllByText("去背景").length).toBeGreaterThan(0);
    expect(document.querySelector("[data-board-tool-source]")?.textContent).toBe("我的抠图 · ");
    expect(document.querySelector("strong")?.textContent).toBe("主体");
  });

  it("内置工具不挂「内置」,也不挂任何出处", () => {
    renderAction(action(), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-tool-source]")).toBeNull();
    expect(document.body.textContent).not.toContain("boardToolBuiltin");
  });

  it("格子里、格子上方那一行用的是这个工具自己的图标,不是一把通用的扳手", () => {
    renderAction(action(), { tool: TRANSLATE });
    expect(iconsIn("[data-board-tool-icon]").join(" ")).toContain("lucide-languages");
    expect(document.querySelector("svg.lucide-wrench")).toBeNull();
    expect(document.querySelectorAll("svg.lucide-languages").length).toBe(2);
    cleanup();
    renderAction(action(), { tool: TOOL });
    expect(iconsIn("[data-board-tool-icon]").join(" ")).toContain("lucide-image");
    cleanup();
    //: 清单还没到:先用工具格的通用图标,不空着。
    renderAction(action());
    expect(iconsIn("[data-board-tool-icon]").join(" ")).toContain("lucide-wrench");
  });

  it("空着:说清吃什么(没接上是虚的)、必填还没选的设置、产出什么", () => {
    renderAction(action(), { tool: TRANSLATE });
    const input = document.querySelector<HTMLElement>('[data-board-tool-input="text"]')!;
    expect(input.dataset.connected).toBe("false");
    expect(input.textContent).toBe("接boardKindNote或boardKindDocument");
    expect(document.querySelector('[data-board-tool-setting="target_lang"]')?.textContent).toBe("boardToolUnset");
    expect(document.querySelector("[data-board-tool-products]")?.textContent).toBe("boardKindNote");
    expect(document.querySelector("[data-board-tool-summary]")?.textContent).toContain("目标语言");
    cleanup();
    renderAction(action(), { tool: { ...TRANSLATE, inputs: [{ key: "asset_id", label: "素材", kinds: ["image", "video", "audio"] }] } });
    expect(document.querySelector('[data-board-tool-input="asset_id"]')?.textContent).toBe("接boardKindImage、boardKindVideo或boardKindAudio");
  });

  it("接上了:那一格的名字;设置按显示名;素材产出按输出名", () => {
    const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, text: "早上好" };
    renderAction(action(), {
      tool: { ...TRANSLATE, inputs: [{ ...TRANSLATE.inputs[0], source: note }], settings: [{ key: "target_lang", label: "目标语言", value: "英语" }] },
    });
    const input = document.querySelector<HTMLElement>('[data-board-tool-input="text"]')!;
    expect(input.dataset.connected).toBe("true");
    expect(input.textContent).toBe("早上好");
    expect(document.querySelector('[data-board-tool-setting="target_lang"]')?.textContent).toBe("英语");
    cleanup();
    renderAction(action(), { tool: TOOL });
    expect(document.querySelector("[data-board-tool-products]")?.textContent).toBe("抠好的图");
  });

  it("在跑、跑挂了的时候不摆摘要(那一块留给状态)", () => {
    renderAction(action({ status: "running", job_id: "job-1" }), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-tool-summary]")).toBeNull();
    cleanup();
    renderAction(action({ status: "failed", error: "x" }), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-tool-summary]")).toBeNull();
    cleanup();
    //: 跑完了:摘要回来,外壳按成功上色。
    renderAction(action({ status: "succeeded" }), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-tool-summary]")).not.toBeNull();
    expect(document.querySelector("[data-board-run-status]")?.getAttribute("data-board-run-status")).toBe("succeeded");
  });

  it("在跑:扫光占位 + 进度 + 停止,停止交给上层取消那一轮", async () => {
    const onStop = vi.fn();
    renderAction(action({ status: "running", job_id: "job-1" }), { tool: TOOL, onStop });
    expect(document.querySelector("[data-slot=skeleton]")).not.toBeNull();
    expect(await screen.findByText(/40%/)).toBeTruthy();
    fireEvent.click(document.querySelector<HTMLElement>("[data-board-stop]")!);
    expect(onStop).toHaveBeenCalledWith("a1");
  });

  it("跑挂了写原因;清单里查不到这个工具时说它用不了", () => {
    renderAction(action({ status: "failed", error: "上游挂了" }), { tool: TOOL });
    expect(screen.getByRole("alert").textContent).toContain("上游挂了");
    cleanup();
    renderAction(action(), { tool: null });
    expect(document.body.textContent).toContain("boardToolUnavailable");
    expect(document.querySelector("[data-board-stop]")).toBeNull();
  });
});

describe("工具交回的结构化数据落成的便签", () => {
  it("按代码排版(等宽)", () => {
    const Note = BOARD_NODE_TYPES.note;
    const item: BoardItem = { id: "n", kind: "note", x: 0, y: 0, text: '{\n  "a": 1\n}', text_format: "json" };
    const props = { id: "n", data: { item, onText: vi.fn(), onAspect: vi.fn() }, selected: false } as unknown as React.ComponentProps<
      typeof Note
    >;
    render(<Note {...props} />);
    const body = document.querySelector<HTMLElement>('[data-text-format="json"]')!;
    expect(body.className).toContain("font-mono");
    expect(body.textContent).toContain('"a": 1');
  });
});
