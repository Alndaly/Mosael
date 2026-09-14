/** @vitest-environment jsdom */
/**
 * 保存失败这条提示是**常驻在页面上**的 —— toast 会自己消失,它不会。所以它得经得起一直看:
 *
 * 1. 那句话是给人读的。`String(err)` 走 `Error.prototype.toString()`,会把 `name` 贴回句首,
 *    于是后端那句干净的「笔记不存在」在界面上变成「ApiError: 笔记不存在」。
 * 2. 失败不该配一个 ✓。此前状态位无论什么状态都渲染 `<Check/>`,「保存失败」旁边顶着个对勾。
 * 3. 两个动作得看起来像动作。此前它们跟着整条红字一起变红,读起来是句子的一部分。
 */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError } from "@/api/transport";
import { emptyNote, type Note } from "@/api/domains/notes";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
vi.mock("./NoteEditor", () => ({ NoteEditor: () => <div data-testid="editor" />, NoteReader: () => <div /> }));
const saveNote = vi.fn();
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: (note: Note) => saveNote(note) as Promise<Note>,
}));

const { NoteDocument } = await import("./NotesView");

afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "草稿", revision: 3, created_at: "2026-09-14", updated_at: "2026-09-14" };

async function failToSave() {
  // 本机草稿和服务端版本不一致 → 挂载即进「草稿待保存」,700ms 后自动保存,然后失败。
  localStorage.setItem(`mosael.note.draft.ws.n1`, JSON.stringify({ ...note, markdown: "还没存上的一段" }));
  mount();
  return await waitFor(() => screen.getByRole("alert"), { timeout: 3000 });
}

function mount() {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} />
    </QueryClientProvider>,
  );
}

it("后端那句话原样出现,前面不带类名", async () => {
  saveNote.mockRejectedValue(new ApiError("笔记不存在", 404, '{"detail":"笔记不存在"}'));
  const strip = await failToSave();
  expect(strip.textContent).toContain("笔记不存在");
  // `String(err)` 会把 "ApiError: " 贴回句首 —— 类名是给写代码的人看的。
  expect(strip.textContent).not.toContain("ApiError");
});

it("失败不配一个对勾", async () => {
  saveNote.mockRejectedValue(new ApiError("笔记不存在", 404, "{}"));
  await failToSave();
  const status = document.querySelector(".note-status");
  expect(status?.getAttribute("data-state")).toBe("error");
  expect(status?.querySelector(".lucide-check")).toBeNull();
});

it("两个动作是真按钮,不是红字的一部分", async () => {
  saveNote.mockRejectedValue(new ApiError("笔记不存在", 404, "{}"));
  const strip = await failToSave();
  // 和「正在看历史版本」那条提示带同一套写法:一条通知带 + 里面的按钮各自可点。
  expect(strip.className).toBe("note-error-notice");
  expect(strip.querySelectorAll("button")).toHaveLength(2);
  // 内容对着正文那一栏排 —— 通知带铺满整行,里面这行跟标题、正文一样居中。
  expect(strip.querySelector(".note-notice-row")).not.toBeNull();
});
