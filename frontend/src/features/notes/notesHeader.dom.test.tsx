/** @vitest-environment jsdom */
/**
 * 笔记顶栏:左边全是编辑格式,右边是文档级的东西;「阅读」模式整个去掉,只剩编辑和 Markdown。
 *
 * - Markdown 是一颗能按下的切换,不再是三段式的分段控件;按下时左边那组格式收起(Markdown 里点了也不会有反应);
 * - 高亮和选区工具条一致,顶栏也有;
 * - 窄了按优先级把低频的组收进「更多格式」,不换行、不重叠。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";
import { hoverHint } from "@/test/hint";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: vi.fn(async (note: Note) => note),
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

//: 格式那一栏有多宽由测试说了算(jsdom 没有版面)。
const layout = vi.hoisted(() => ({ width: 1200, observers: [] as ResizeObserverCallback[] }));
vi.stubGlobal("ResizeObserver", class {
  constructor(private callback: ResizeObserverCallback) { layout.observers.push(callback); }
  observe(target: Element) { this.callback([{ target, contentRect: { width: layout.width } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver); }
  unobserve() {}
  disconnect() {}
});

const { NoteDocument } = await import("./NotesView");
const { visibleFormatGroups } = await import("./NoteFormatToolbar");

const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "周报", markdown: "周一开了会。", revision: 1, created_at: "x", updated_at: "x" };

beforeEach(() => { layout.width = 1200; layout.observers = []; });
afterEach(() => { cleanup(); localStorage.clear(); });

function mount() {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} onToggleAgent={() => {}} />
    </QueryClientProvider>,
  );
}
const header = () => document.querySelector(".note-document-header") as HTMLElement;
const format = () => within(header()).queryByRole("toolbar", { name: "格式工具" });

it("只剩编辑和 Markdown:没有「阅读」,Markdown 是一颗能按下的切换;按下时格式那一组收起", async () => {
  mount();
  await waitFor(() => expect(format()).not.toBeNull());
  expect(within(header()).queryByRole("button", { name: "阅读" })).toBeNull();
  expect(within(header()).queryByRole("button", { name: "编辑" })).toBeNull();
  expect(within(header()).queryByRole("group", { name: "查看方式" })).toBeNull();

  const markdown = within(header()).getByRole("button", { name: "Markdown" });
  expect(markdown).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(markdown);

  expect(markdown).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", { name: "笔记正文" }).tagName).toBe("TEXTAREA");
  //: Markdown 里没有能点的格式按钮(收起,而不是摆着点了没反应)。
  expect(format()).toBeNull();
  expect(within(header()).queryByRole("button", { name: "粗体" })).toBeNull();

  fireEvent.click(markdown);
  expect(markdown).toHaveAttribute("aria-pressed", "false");
  await waitFor(() => expect(format()).not.toBeNull());
});

it("左边全是编辑格式(含高亮,和选区工具条一致),右边依次是保存状态、Markdown、AI 助手、收藏、笔记操作", async () => {
  mount();
  await waitFor(() => expect(format()).not.toBeNull());
  const toolbar = format()!;
  for (const name of ["段落样式", "粗体", "斜体", "删除线", "高亮", "无序列表", "有序列表", "任务列表", "插入", "网页链接", "表格", "撤销", "重做"]) {
    expect(within(toolbar).getByRole("button", { name }), name).toBeInTheDocument();
  }
  const right = header().querySelector(".note-header-actions")!;
  const labels = [...right.children].map((one) => one.getAttribute("aria-label") ?? one.getAttribute("data-slot"));
  expect(labels).toEqual(["save-status", "Markdown", "wfAgentTitle", "收藏", "笔记操作"]);

  //: 高亮按钮作用在选区上,已高亮的再点取消。
  const editor = (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
  act(() => { editor.commands.setTextSelection({ from: 1, to: 3 }); });
  fireEvent.click(within(toolbar).getByRole("button", { name: "高亮" }));
  expect(editor.getMarkdown()).toContain("==周一==");
  await waitFor(() => expect(within(toolbar).getByRole("button", { name: "高亮" })).toHaveAttribute("aria-pressed", "true"));
  fireEvent.click(within(toolbar).getByRole("button", { name: "高亮" }));
  expect(editor.getMarkdown()).not.toContain("==");
});

it("保存状态是一块固定的位置:文字在悬停说明里也有一份(窄了只剩图标),切换状态时不推着别的按钮动", async () => {
  mount();
  const status = header().querySelector("[data-slot='save-status']") as HTMLElement;
  expect(status.className).toContain("note-status");
  expect(await hoverHint(status)).toBe("已保存");
});

it("宽的时候一组不收;窄了先收插入、撤销,再收列表,收进「更多格式」—— 菜单里点了照样作用在正文上", async () => {
  mount();
  await waitFor(() => expect(format()).not.toBeNull());
  expect(within(format()!).queryByRole("button", { name: "更多格式" })).toBeNull();

  layout.width = 320;
  act(() => { for (const observer of layout.observers) observer([{ contentRect: { width: 320 } } as unknown as ResizeObserverEntry], {} as ResizeObserver); });

  const toolbar = format()!;
  expect(within(toolbar).getByRole("button", { name: "粗体" })).toBeInTheDocument();
  for (const name of ["插入", "网页链接", "表格", "撤销", "重做", "无序列表"]) {
    expect(within(toolbar).queryByRole("button", { name }), name).toBeNull();
  }
  fireEvent.click(within(toolbar).getByRole("button", { name: "更多格式" }));
  const menu = await screen.findByRole("menu", { name: "更多格式" });
  for (const name of ["无序列表", "插入 3 × 3 表格", "撤销"]) expect(within(menu).getByRole("menuitem", { name }), name).toBeInTheDocument();

  const editor = (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
  fireEvent.click(within(menu).getByRole("menuitem", { name: "无序列表" }));
  expect(editor.isActive("bulletList")).toBe(true);
});

it("收的先后:插入那组 → 撤销重做 → 列表 → 粗体那组;段落类型一直在", () => {
  //: 估的宽度:段落 96、粗体那组 126、列表 94、插入那组 160、撤销重做 62;组间 13;「更多格式」13 + 30。
  expect(visibleFormatGroups(Infinity)).toEqual(["block", "marks", "lists", "insert", "history"]);
  expect(visibleFormatGroups(590)).toEqual(["block", "marks", "lists", "insert", "history"]);
  expect(visibleFormatGroups(589)).toEqual(["block", "marks", "lists", "history"]);
  expect(visibleFormatGroups(459)).toEqual(["block", "marks", "lists"]);
  expect(visibleFormatGroups(384)).toEqual(["block", "marks"]);
  expect(visibleFormatGroups(120)).toEqual(["block"]);
  //: 量到了就按量到的算:「插入」实际只有 76 宽时,590 以下也还放得下。
  expect(visibleFormatGroups(580, { insert: 76 + 64 })).toEqual(["block", "marks", "lists", "insert", "history"]);
});
