/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

/**
 * 工具格在画布上的样子,和它交回的结构化数据落成的便签。
 *
 * 工具格自己不放产出:画的是「这是什么工具、从哪来、现在怎样」—— 在跑时扫光 + 停止按钮,
 * 跑挂了写原因,清单里查不到时说它用不了。
 */

vi.mock("@xyflow/react", () => ({
  Handle: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) => selector({ transform: [0, 0, 1] }),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getJob: vi.fn(async () => ({ id: "job-1", progress: 0.4 })),
}));

import { BOARD_NODE_TYPES, type BoardToolFace } from "./boardNodes";

afterEach(cleanup);

const TOOL: BoardToolFace = { label: "去背景", description: "把**主体**抠出来", plugin: "我的抠图" };

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
  it("没起名时用工具的名字;标出它来自哪个插件;说明按行内 Markdown 渲染", () => {
    renderAction(action(), { tool: TOOL });
    expect(screen.getAllByText("去背景").length).toBeGreaterThan(0);
    expect(document.querySelector("[data-board-tool-source]")?.textContent).toBe("我的抠图");
    expect(document.querySelector("strong")?.textContent).toBe("主体");
  });

  it("内置节点标「内置」", () => {
    renderAction(action(), { tool: { ...TOOL, plugin: "" } });
    expect(document.querySelector("[data-board-tool-source]")?.textContent).toBe("boardToolBuiltin");
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
