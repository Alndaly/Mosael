/** @vitest-environment jsdom */
/**
 * 标题里用拼音打中文,组词停得久一点(选词)自动保存就到点了。服务端回来的标题是规整过的
 * (首尾空白去掉),此前那一份直接 setDraft 回框里:组词中的框被写一遍,组词断掉,拼音上屏,
 * 刚打的空格也被吃掉。
 */
import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";
import { composeWithIme, watchValueWrites } from "@/test/ime";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
vi.mock("./NoteEditor", () => ({ NoteEditor: ({ title }: { title?: React.ReactNode }) => <div>{title}</div>, NoteReader: () => <div /> }));
const saveNote = vi.fn();
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  saveNote: (note: Note) => saveNote(note) as Promise<Note>,
}));

const { NoteDocument } = await import("./NotesView");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  //: 服务端照实收下,但标题首尾空白去掉 —— 和后端一样。
  saveNote.mockImplementation(async (sent: Note) => ({ ...sent, title: sent.title.trim(), revision: sent.revision + 1 }));
});
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); vi.useRealTimers(); });

const note: Note = { ...emptyNote, id: "n1", workspace_id: "ws", title: "", revision: 3, created_at: "x", updated_at: "x" };

it("组词期间自动保存回来了:框里的字不被改写,上屏后标题是中文、后面的空格还在", async () => {
  const controller = React.createRef<null>() as React.MutableRefObject<null>;
  render(<QueryClientProvider client={new QueryClient()}><NoteDocument note={note} controller={controller as never} focus={false} onFocus={() => {}} /></QueryClientProvider>);
  const title = document.querySelector<HTMLTextAreaElement>("textarea.note-title")!;
  const writes = watchValueWrites(title);

  //: 先打一个字加空格(英文直接上屏),再开始组词、停在选词上 —— 这时自动保存到点。
  act(() => {
    title.focus();
  });
  composeWithIme(title, ["h", "he"], "和 ");
  const setNative = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  act(() => {
    title.dispatchEvent(new CompositionEvent("compositionstart", { data: "", bubbles: true }));
    setNative.call(title, "和 ni");
    title.dispatchEvent(new InputEvent("input", { data: "i", inputType: "insertCompositionText", isComposing: true, bubbles: true }));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(saveNote).toHaveBeenCalled();
  act(() => {
    setNative.call(title, "和 你");
    title.dispatchEvent(new InputEvent("input", { data: "你", inputType: "insertCompositionText", isComposing: true, bubbles: true }));
    title.dispatchEvent(new CompositionEvent("compositionend", { data: "你", bubbles: true }));
  });

  expect(writes).toEqual([]);
  expect(title.value).toBe("和 你");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect((saveNote.mock.calls.at(-1)![0] as Note).title).toBe("和 你");
  expect(saveNote.mock.calls.map(([sent]) => (sent as Note).title).filter((one) => /[a-z]/i.test(one))).toEqual([]);
});
