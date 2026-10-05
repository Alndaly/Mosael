/** @vitest-environment jsdom */
/**
 * 插入表格的格子选择器:笔记格式栏的「插入表格」点开是一张格子,移到哪一格亮到哪一格、下面写着行 × 列,点下去插入这么大的表格。
 *
 * 用真的笔记编辑器验:亮的是不是从左上角到指着的那一格、移到边上会不会往外长、插进去的表格是不是这么大(第一行是表头,
 * 和此前直接插入的一样)、键盘走不走得通、Esc 收起时什么都不插。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNotes: vi.fn(async () => []),
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteEditor } = await import("./NoteEditor");

afterEach(() => { cleanup(); });

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoteEditor markdown={"周一开了会。"} onChange={() => {}} onReference={() => {}} workspaceId="ws" noteId="n1" />
    </QueryClientProvider>,
  );
}

async function editor(): Promise<Editor> {
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());
  return (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
}

const tableButton = () => within(screen.getByRole("toolbar", { name: "格式工具" })).getByRole("button", { name: "插入表格" });
async function openPicker(): Promise<HTMLElement> {
  fireEvent.click(tableButton());
  return screen.findByRole("grid", { name: "插入表格" });
}
const cell = (grid: HTMLElement, name: string) => within(grid).getByRole("gridcell", { name });
const lit = (grid: HTMLElement) => within(grid).getAllByRole("gridcell").filter((one) => one.getAttribute("aria-selected") === "true").map((one) => one.getAttribute("aria-label"));
const shown = (grid: HTMLElement) => ({ rows: within(grid).getAllByRole("row").length, cells: within(grid).getAllByRole("gridcell").length });

/** 文档里那张表:几行、几列、第一行是不是表头。 */
function table(instance: Editor) {
  let found: { rows: number; cols: number; header: boolean } | null = null;
  instance.state.doc.descendants((node) => {
    if (found || node.type.name !== "table") return !found;
    const first = node.firstChild!;
    found = { rows: node.childCount, cols: first.childCount, header: first.firstChild!.type.name === "tableHeader" };
    return false;
  });
  return found;
}

it("按钮叫「插入表格」;移到哪一格,从左上角到那一格都亮起来、下面写着行 × 列;点下去插入这么大的表格,第一行是表头", async () => {
  mount();
  const instance = await editor();
  const grid = await openPicker();
  expect(shown(grid)).toEqual({ rows: 8, cells: 64 });

  fireEvent.mouseEnter(cell(grid, "3 × 4"));
  expect(lit(grid)).toHaveLength(12);
  expect(lit(grid)).toEqual(expect.arrayContaining(["1 × 1", "1 × 4", "3 × 1", "3 × 4"]));
  expect(lit(grid)).not.toContain("4 × 4");
  expect(lit(grid)).not.toContain("3 × 5");
  expect(grid.parentElement!.textContent).toBe("3 × 4");

  fireEvent.mouseEnter(cell(grid, "2 × 6"));
  expect(lit(grid)).toHaveLength(12);
  expect(grid.parentElement!.textContent).toBe("2 × 6");

  fireEvent.click(cell(grid, "2 × 6"));
  expect(table(instance)).toEqual({ rows: 2, cols: 6, header: true });
  await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
  //: 插完接着打字:焦点在正文里(光标在表格第一格),不被浮层收起时抢回按钮上。
  await waitFor(() => expect(document.activeElement).toBe(instance.view.dom));
  expect(instance.state.selection.$from.parent.type.name).toBe("paragraph");
  expect(instance.state.selection.$from.node(-1).type.name).toBe("tableHeader");
});

it("移到最后一行 / 一列时往外长一格,最多 10 × 10;往回移又缩回 8 × 8", async () => {
  mount();
  await editor();
  const grid = await openPicker();

  fireEvent.mouseEnter(cell(grid, "8 × 3"));
  expect(shown(grid)).toEqual({ rows: 9, cells: 72 });
  fireEvent.mouseEnter(cell(grid, "9 × 8"));
  expect(shown(grid)).toEqual({ rows: 10, cells: 90 });
  fireEvent.mouseEnter(cell(grid, "10 × 9"));
  expect(shown(grid)).toEqual({ rows: 10, cells: 100 });
  fireEvent.mouseEnter(cell(grid, "10 × 10"));
  expect(shown(grid)).toEqual({ rows: 10, cells: 100 });
  expect(lit(grid)).toHaveLength(100);

  fireEvent.mouseEnter(cell(grid, "2 × 2"));
  expect(shown(grid)).toEqual({ rows: 8, cells: 64 });
});

it("键盘:打开时焦点在第一格,方向键挪(焦点和高亮一起走),回车插入", async () => {
  mount();
  const instance = await editor();
  const grid = await openPicker();
  await waitFor(() => expect(document.activeElement).toBe(cell(grid, "1 × 1")));
  //: 只有指着的那一格在 Tab 序列里,Tab 一下就出了格子,不用走完 64 格。
  expect(within(grid).getAllByRole("gridcell").filter((one) => one.tabIndex === 0)).toEqual([cell(grid, "1 × 1")]);

  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
  expect(document.activeElement).toBe(cell(grid, "2 × 3"));
  expect(lit(grid)).toHaveLength(6);
  expect(grid.parentElement!.textContent).toBe("2 × 3");
  //: 左上角再往外挪不动。
  fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
  expect(document.activeElement).toBe(cell(grid, "1 × 3"));
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });

  fireEvent.keyDown(document.activeElement!, { key: "Enter" });
  expect(table(instance)).toEqual({ rows: 3, cols: 3, header: true });
  await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
});

it("键盘一路往外挪也会长,到 10 × 10 为止", async () => {
  mount();
  const instance = await editor();
  const grid = await openPicker();
  await waitFor(() => expect(document.activeElement).toBe(cell(grid, "1 × 1")));
  for (let i = 0; i < 12; i += 1) fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  for (let i = 0; i < 12; i += 1) fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  expect(document.activeElement).toBe(cell(grid, "10 × 10"));
  fireEvent.keyDown(document.activeElement!, { key: "Enter" });
  expect(table(instance)).toEqual({ rows: 10, cols: 10, header: true });
});

it("Esc 收起,什么都不插,焦点回到按钮上", async () => {
  mount();
  const instance = await editor();
  const grid = await openPicker();
  await waitFor(() => expect(document.activeElement).toBe(cell(grid, "1 × 1")));
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
  expect(table(instance)).toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(tableButton()));
});

it("光标在表格里时,那颗按钮叫「表格」,点开是加行、加列、删表格(不是格子)", async () => {
  mount();
  const instance = await editor();
  fireEvent.click(cell(await openPicker(), "2 × 2"));
  expect(table(instance)).toEqual({ rows: 2, cols: 2, header: true });
  await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(instance.view.dom));

  const format = screen.getByRole("toolbar", { name: "格式工具" });
  await waitFor(() => expect(within(format).getByRole("button", { name: "表格" })).toHaveAttribute("aria-pressed", "true"));
  fireEvent.click(within(format).getByRole("button", { name: "表格" }));
  const menu = await screen.findByRole("menu", { name: "表格" });
  expect(screen.queryByRole("grid")).toBeNull();
  fireEvent.click(within(menu).getByRole("menuitem", { name: "在下方插入行" }));
  expect(table(instance)).toEqual({ rows: 3, cols: 2, header: true });
});
