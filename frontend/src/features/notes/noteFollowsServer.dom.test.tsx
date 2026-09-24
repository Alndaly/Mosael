/** @vitest-environment jsdom */
/**
 * 服务端有了更新的一版、这里又没有没存的改动时,文档整份跟上。
 * 此前只认「追加」:别处把它移进回收站,这里照样显示成可编辑、没有回收站提示条。
 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
vi.mock("./NoteEditor", () => ({ NoteEditor: () => <div data-testid="editor" />, NoteReader: () => <div /> }));
const { NoteDocument } = await import("./NotesView");
afterEach(() => { cleanup(); localStorage.clear(); });

const base: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "mosael", markdown: "正文", revision: 3, created_at: "x", updated_at: "x" };

function view(note: Note, client = new QueryClient()) {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  return <QueryClientProvider client={client}><NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} /></QueryClientProvider>;
}

it("别处移进了回收站:打开着的这篇跟上,出现回收站提示条和「移出回收站」", () => {
  const client = new QueryClient();
  const page = render(view(base, client));
  expect(screen.queryByText(/已移入回收站/)).toBeNull();
  page.rerender(view({ ...base, trashed: true, revision: 4 }, client));
  expect(screen.getByText(/已移入回收站/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /移出回收站/ })).toBeInTheDocument();
  expect(document.querySelector(".note-status")?.getAttribute("data-state")).toBe("saved");
});
