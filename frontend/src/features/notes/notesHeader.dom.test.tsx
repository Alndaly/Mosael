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
