/** @vitest-environment jsdom */
/**
 * 智能体改了一段(edit_note 的卡批准了,服务端多了一版):打开着的这篇**当场**变,只变那一段,
 * 而且进撤销历史 —— 点「撤销」退回改之前,退回的那一版照常自动保存。
 *
 * 此前外面来的新一版是整份 setContent:光标被扔回开头,正在看的那一处也跟着跳走。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/react";
import { emptyNote, type Note } from "@/api/domains/notes";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const api = vi.hoisted(() => ({ saveNote: vi.fn(async (note: Note) => ({ ...note, revision: note.revision + 1 })) }));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: api.saveNote,
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteDocument } = await import("./NotesView");
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

const base: Note = {
  ...emptyNote, id: "n1", workspace_id: "ws", title: "周报", revision: 3, save_seq: 3, created_at: "x", updated_at: "x",
  markdown: "开头不动。\n\n要改的一段。\n\n结尾也不动。",
};

function view(note: Note, client: QueryClient) {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  return <QueryClientProvider client={client}><NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} /></QueryClientProvider>;
}
const prose = () => document.querySelector(".ProseMirror")?.textContent ?? "";
const status = () => document.querySelector(".note-status")?.getAttribute("data-state");
const editor = () => (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
/** 光标前面紧挨着的两个字。 */
const beforeCaret = () => { const { from } = editor().state.selection; return editor().state.doc.textBetween(Math.max(0, from - 2), from); };

it("服务端改了一段:编辑器当场变、不算本地草稿;撤销退回改之前,退回的那一版自动保存", async () => {
  const client = new QueryClient();
  const page = render(view(base, client));
  await waitFor(() => expect(prose()).toContain("要改的一段。"));
  //: 用户的光标停在「结尾」后面。
  act(() => {
    let caret = 0;
    editor().state.doc.descendants((node, pos) => { if (node.isText && node.text!.includes("结尾")) caret = pos + node.text!.indexOf("结尾") + 2; });
    editor().commands.setTextSelection(caret);
  });
  expect(beforeCaret()).toBe("结尾");

  page.rerender(view({ ...base, revision: 4, save_seq: 4, markdown: "开头不动。\n\n智能体改好的一段。\n\n结尾也不动。" }, client));

  await waitFor(() => expect(prose()).toContain("智能体改好的一段。"));
  expect(prose()).toContain("开头不动。");
  //: 只换了那一段:光标还在「结尾」后面,没被扔回开头。
  expect(beforeCaret()).toBe("结尾");
  expect(status()).toBe("saved");
  expect(api.saveNote).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "撤销" }));

  await waitFor(() => expect(prose()).toContain("要改的一段。"));
  expect(prose()).not.toContain("智能体改好的一段。");
  expect(status()).toBe("draft");
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 800)); });
  await waitFor(() => expect(api.saveNote).toHaveBeenCalled());
  const saved = api.saveNote.mock.calls.at(-1)![0];
  expect(saved.revision).toBe(4);
  expect(saved.markdown).toContain("要改的一段。");
  expect(saved.markdown).not.toContain("智能体改好的一段。");
});
