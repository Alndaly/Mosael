/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

/**
 * 工具格在画布上的样子,和它交回的结构化数据落成的便签。
 *
 * 工具格长得像它要产出的那种内容的空格子(出图的是一块空图片格,翻译是一张空便签):同一个外壳、正中
 * 一枚淡淡的图标 —— 是这个工具自己的图标;格子里没有「吃什么 / 设置 / 产出」那张小字表,缺必填输入时
 * 至多一句「接……」。在跑、跑挂了和生成格同一个外壳(扫光 + 进度 + 停止、失败写原因)。
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
  kind: "image",
  missing: ["image"],
};

const TRANSLATE: BoardToolFace = {
  label: "翻译",
  description: "把便签或文档里的文字翻成另一种语言",
  plugin: "",
  icon: Languages,
  kind: "note",
  missing: ["note", "document"],
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

const root = () => document.querySelector<HTMLElement>("[data-board-action]")!;

describe("工具格", () => {
  it("没起名时格子上方写工具名;插件工具在名字后面淡淡地点名插件;说明悬停看,格子里不写字", () => {
    renderAction(action(), { tool: TOOL });
    const label = document.querySelector<HTMLElement>("[data-board-node-label]")!;
    expect(label.textContent).toContain("去背景");
    expect(label.querySelector("[data-board-node-label-secondary]")?.textContent).toContain("我的抠图");
    expect(root().getAttribute("title")).toBe("把主体抠出来");
    expect(document.querySelector("strong")).toBeNull();
  });

  it("起了名:名字后面带上工具名(和插件名);内置工具不挂出处", () => {
    renderAction({ ...action(), title: "抠封面" }, { tool: TOOL });
    expect(document.querySelector("[data-board-node-label-secondary]")?.textContent).toBe("· 去背景 · 我的抠图");
    cleanup();
    renderAction(action(), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-node-label-secondary]")).toBeNull();
  });

  it("长成它要产出的那种内容的空格子:出图的是一块图片格,翻译是一张便签 —— 没有那张小字表", () => {
    renderAction(action(), { tool: TOOL });
    expect(root().dataset.boardToolKind).toBe("image");
    //: 和空的图片格同一个外壳(ImageNode:rounded-lg、面板底、安静的实线边)。
    expect(root().className).toContain("rounded-lg");
    expect(root().className).toContain("bg-panel");
    expect(document.querySelector("[data-board-empty-slot]")).not.toBeNull();
    for (const gone of ["[data-board-tool-summary]", "dl", "dt", "[data-board-tool-input]", "[data-board-tool-setting]", "[data-board-tool-products]"]) {
      expect(document.querySelector(gone), gone).toBeNull();
    }
    cleanup();
    renderAction(action(), { tool: TRANSLATE });
    expect(root().dataset.boardToolKind).toBe("note");
    //: 产出文字的工具格**不涂便签的颜色**:便签黄只属于真正的便签,否则一格翻译放在画布上和一张便签分不出来。
    //: 它和空的图片格同一块中性的面板底,会产出什么由正中的图标说。
    expect(root().className).toContain("rounded-lg");
    expect(root().className).toContain("bg-panel");
    expect(root().className).not.toContain("#f5c518");
  });

  it("正中那枚图标是这个工具自己的(格子上方那一行也是),不是一把通用的扳手", () => {
    renderAction(action(), { tool: TRANSLATE });
    expect(iconsIn("[data-board-empty-slot]").join(" ")).toContain("lucide-languages");
    expect(document.querySelector("svg.lucide-wrench")).toBeNull();
    expect(document.querySelectorAll("svg.lucide-languages").length).toBe(2);
    cleanup();
    //: 清单还没到:先用工具格的通用图标,不空着。
    renderAction(action());
    expect(iconsIn("[data-board-empty-slot]").join(" ")).toContain("lucide-wrench");
  });

  it("缺必填输入时,图标下面至多一句「接……」;不缺就什么都不写", () => {
    renderAction(action(), { tool: TRANSLATE });
    expect(document.querySelector("[data-board-empty-hint]")?.textContent).toBe("接boardKindNote或boardKindDocument");
    cleanup();
    renderAction(action(), { tool: { ...TRANSLATE, missing: ["image", "video", "audio"] } });
    expect(document.querySelector("[data-board-empty-hint]")?.textContent).toBe("接boardKindImage、boardKindVideo或boardKindAudio");
    cleanup();
    renderAction(action(), { tool: { ...TRANSLATE, missing: null } });
    expect(document.querySelector("[data-board-empty-hint]")).toBeNull();
    expect(root().textContent).toBe("翻译");
  });

  it("在跑:和生成格同一个外壳 —— 扫光 + 进度 + 停止,停止交给上层取消那一轮", async () => {
    const onStop = vi.fn();
    renderAction(action({ status: "running", job_id: "job-1" }), { tool: TOOL, onStop });
    expect(document.querySelector("[data-slot=skeleton]")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("boardToolRunning");
    expect(await screen.findByText(/40%/)).toBeTruthy();
    fireEvent.click(document.querySelector<HTMLElement>("[data-board-stop]")!);
    expect(onStop).toHaveBeenCalledWith("a1");
  });

  it("跑挂了:说「运行失败」和原因(和生成失败同一种样子);跑完:回到安静的空格子,不留彩色描边", () => {
    renderAction(action({ status: "failed", error: "上游挂了" }), { tool: TOOL });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("boardNodeRunFailed");
    expect(alert.textContent).toContain("上游挂了");
    cleanup();
    renderAction(action({ status: "succeeded" }), { tool: TRANSLATE });
    expect(root().dataset.boardRunStatus).toBe("succeeded");
    expect(document.querySelector("[data-board-empty-slot]")).not.toBeNull();
    expect(root().className).not.toMatch(/ring-success|border-success/);
  });

  it("清单里查不到这个工具时说它用不了(一句短的,全文悬停看);没有停止", () => {
    renderAction(action(), { tool: null });
    expect(document.querySelector("[data-board-empty-hint]")?.textContent).toBe("boardToolUnavailableShort");
    expect(root().getAttribute("title")).toBe("boardToolUnavailable");
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
