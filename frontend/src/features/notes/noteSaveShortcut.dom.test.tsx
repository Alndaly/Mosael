/** @vitest-environment jsdom */
/**
 * 在笔记正文里按 ⌘S:欠着的这一份马上存,不等自动保存那 700ms;网页版也不弹浏览器的「存储网页」。
 * 此前笔记页没人接 ⌘S(见 lib/saveShortcut)。
 */
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/react";
import { emptyNote, type Note } from "@/api/domains/notes";
import { installSaveShortcut } from "@/lib/saveShortcut";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const api = vi.hoisted(() => ({
  saveNote: vi.fn(async (note: Note) => ({ ...note, revision: note.revision + 1, save_seq: note.save_seq + 1 })),
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: api.saveNote,
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteDocument } = await import("./NotesView");
let uninstall: () => void = () => undefined;
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  uninstall = installSaveShortcut(window);
});
afterEach(() => {
  uninstall();
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

const editor = () => (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;

it("正文里改了一个字就按 ⌘S:马上存(不等 700ms),键被拦下", async () => {
  const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "周报", markdown: "# 周报\n\n正文\n", revision: 1, save_seq: 1, created_at: "x", updated_at: "x" };
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(document.querySelector(".ProseMirror")).not.toBeNull());
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  act(() => { editor().chain().setTextSelection(2).insertContent("本").run(); });

  const event = new KeyboardEvent("keydown", { key: "s", code: "KeyS", metaKey: true, bubbles: true, cancelable: true });
  act(() => void document.querySelector(".ProseMirror")!.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(50); });

  expect(api.saveNote).toHaveBeenCalledTimes(1);
  expect(api.saveNote.mock.calls[0][0].markdown).toContain("# 周本报");
});
