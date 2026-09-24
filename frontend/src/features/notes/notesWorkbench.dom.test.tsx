/** @vitest-environment jsdom */
/**
 * 笔记页这一轮修的几件事:
 * - 换篇时光标放回开头 —— 此前按旧位置映射到新文档末尾,新笔记以列表结尾时「无序列表」一打开就亮着;
 * - 记住每个工作区最后打开的那篇 —— 此前切到别的页再回来就是一片空;
 * - 拖进来的 .md 直接成笔记,一次可以好几个,不认识的文件不碰。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const api = vi.hoisted(() => ({
  listNotes: vi.fn(async () => [] as Note[]),
  getNote: vi.fn(async (_ws: string, id: string) => ({ id } as Note)),
  createNote: vi.fn(async (_ws: string, body: Partial<Note>) => ({ id: `new-${body.title}` } as Note)),
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNotes: api.listNotes,
  getNote: api.getNote,
  createNote: api.createNote,
}));

// 工具栏吸顶用它判断是否滚过了哨兵;jsdom 没有。
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteEditor } = await import("./NoteEditor");
const { NotesView } = await import("./NotesView");

afterEach(() => { cleanup(); localStorage.clear(); window.location.hash = ""; vi.clearAllMocks(); });

const note = (id: string, title: string): Note => ({ ...emptyNote, id, workspace_id: "ws", title, revision: 1, created_at: "2026-09-24", updated_at: "2026-09-24" });

it("换成另一篇以列表结尾的笔记,「无序列表」不会自己亮", async () => {
  const props = { onChange: () => {}, onReference: () => {}, workspaceId: "ws", noteId: "a" };
  const view = render(<NoteEditor {...props} markdown={"第一篇,一段普通文字"} />);
  await screen.findByRole("button", { name: "无序列表" });
  view.rerender(<NoteEditor {...props} noteId="b" markdown={"第二篇\n\n- 甲\n- 乙"} />);
  await waitFor(() => expect(document.querySelector(".ProseMirror")?.textContent).toContain("乙"));
  expect(screen.getByRole("button", { name: "无序列表" })).not.toHaveAttribute("aria-pressed", "true");
});

function mountView() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NotesView workspace={{ id: "ws" } as never} />
    </QueryClientProvider>,
  );
}

it("切走再回来,打开的还是刚才那篇", async () => {
  api.getNote.mockImplementation(async (_ws: string, id: string) => note(id, "刚才那篇"));
  window.location.hash = "#/notes?note=n7";
  const first = mountView();
  await waitFor(() => expect(api.getNote).toHaveBeenCalledWith("ws", "n7"));
  first.unmount();

  // 切到别的页再回来:地址里不再带这篇笔记。
  window.location.hash = "#/notes";
  api.getNote.mockClear();
  mountView();
  await waitFor(() => expect(api.getNote).toHaveBeenCalledWith("ws", "n7"));
  expect(window.location.hash).toContain("note=n7");
});

it("拖进来几个 .md 各成一篇,别的文件不碰,建完打开最后一篇", async () => {
  const view = mountView();
  const layout = view.container.querySelector(".notes-layout")!;
  const files = [
    new File(["# 甲\n正文"], "甲.md", { type: "text/markdown" }),
    new File(["x"], "照片.png", { type: "image/png" }),
    new File(["乙的内容"], "乙.markdown", { type: "" }),
  ];
  const dataTransfer = { files, types: ["Files"], items: files.map((f) => ({ kind: "file", type: f.type, getAsFile: () => f })), dropEffect: "none" };
  // 只拖图片:那是往正文里插图,整页不接、不亮遮罩。
  const imageOnly = { files: [files[1]], types: ["Files"], items: [{ kind: "file", type: "image/png", getAsFile: () => files[1] }], dropEffect: "none" };
  fireEvent.dragEnter(layout, { dataTransfer: imageOnly });
  expect(view.container.querySelector(".notes-drop")).toBeNull();

  fireEvent.dragEnter(layout, { dataTransfer });
  expect(view.container.querySelector(".notes-drop")).not.toBeNull();
  fireEvent.drop(layout, { dataTransfer });
  await waitFor(() => expect(api.createNote).toHaveBeenCalledTimes(2));
  expect(api.createNote.mock.calls.map(([, body]) => body)).toEqual([
    { title: "甲", markdown: "# 甲\n正文" },
    { title: "乙", markdown: "乙的内容" },
  ]);
  await waitFor(() => expect(window.location.hash).toContain("note=new-%E4%B9%99"));
});
