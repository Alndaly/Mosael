/** @vitest-environment jsdom */
/**
 * 打开一篇经 API 写入或导入的笔记、什么都不动:**不存,也不出版本**。
 *
 * 编辑器有自己的排版(表格补齐空格、空行数),还会自己补结构 —— 文末是表格时,它在后面补一个空段落好让光标
 * 落得下去(TrailingNode)。这一步挂在随便哪个事务后面(代码高亮挂装饰的那一下就够),此前它被当成
 * 「用户改了」:状态变「草稿待保存」,随后自动保存,离上次编辑超过 5 分钟就多出一版看不出改动的「手动编辑」。
 */
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/react";
import { emptyNote, type Note } from "@/api/domains/notes";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
//: 服务端那一侧:每存一次记一版(和后端一样,保存序号、修订号往前走)。
const server = vi.hoisted(() => ({ revisions: [] as string[] }));
const api = vi.hoisted(() => ({
  saveNote: vi.fn(async (note: Note) => {
    server.revisions.push(note.markdown);
    return { ...note, revision: note.revision + 1, save_seq: note.save_seq + 1 };
  }),
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: api.saveNote,
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteDocument } = await import("./NotesView");
beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); vi.useRealTimers(); });

//: 导入进来的原样:表格没对齐、标题和表格之间多了几行空行、文末就是表格。
const imported = "# 周报\n\n\n\n| 项目 | 进度 |\n|---|---|\n| 剪辑 | 80% |\n| 配音|完成 |\n";

function view(note: Note, client: QueryClient) {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  return <QueryClientProvider client={client}><NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} /></QueryClientProvider>;
}
const editor = () => (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
const status = () => document.querySelector(".note-status")?.getAttribute("data-state");

it("打开一篇带表格和多余空行的导入笔记、不动它:等过自动保存的间隔,没有发起保存,版本数不变", async () => {
  server.revisions = [imported];
  const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "周报", markdown: imported, revision: 1, save_seq: 1, created_at: "x", updated_at: "x" };
  render(view(note, new QueryClient()));
  await waitFor(() => expect(document.querySelector(".ProseMirror table")).not.toBeNull());
  //: 编辑器自己的排版和存着的那份确实不一样 —— 不一样也不该算改动。
  expect(editor().getMarkdown()).not.toBe(imported);

  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

  expect(api.saveNote).not.toHaveBeenCalled();
  expect(server.revisions).toHaveLength(1);
  expect(status()).toBe("saved");
  expect(localStorage.getItem("mosael.note.draft.ws.n1")).toBeNull();
});

it("真改了一个字照常保存:存下去的是编辑器那一版,表格和正文一样不少", async () => {
  server.revisions = [imported];
  const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "周报", markdown: imported, revision: 1, save_seq: 1, created_at: "x", updated_at: "x" };
  render(view(note, new QueryClient()));
  await waitFor(() => expect(document.querySelector(".ProseMirror table")).not.toBeNull());
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  act(() => { editor().chain().setTextSelection(2).insertContent("本").run(); });

  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

  expect(api.saveNote).toHaveBeenCalledTimes(1);
  const saved = api.saveNote.mock.calls[0][0].markdown;
  expect(saved).toContain("# 周本报");
  for (const cell of ["项目", "进度", "剪辑", "80%", "配音", "完成"]) expect(saved).toContain(cell);
  expect(server.revisions).toHaveLength(2);
});
