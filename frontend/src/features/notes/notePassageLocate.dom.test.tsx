/** @vitest-environment jsdom */
/**
 * 气泡里那行摘录点进来:笔记页打开那篇,编辑器把那一段选中、滚到眼前。请求走 lib/deepLink 的信箱 ——
 * 编辑器还没好(笔记还在取)时请求留着,好了再投;投给的不是这篇就不接。
 */
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import type { Editor } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";
import { locateNotePassage } from "@/lib/deepLink";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const toastMessage = vi.fn();
vi.mock("sonner", () => ({ toast: { message: (...args: unknown[]) => toastMessage(...args), error: vi.fn(), success: vi.fn() } }));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteEditor } = await import("./NoteEditor");
afterEach(() => { cleanup(); window.location.hash = ""; toastMessage.mockReset(); });

const props = { onChange: () => {}, onReference: () => {}, workspaceId: "ws" };
const editor = () => (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
const selected = () => { const { from, to } = editor().state.selection; return editor().state.doc.textBetween(from, to); };

it("定位请求投到这篇:那一段被选中", async () => {
  render(<NoteEditor {...props} noteId="n1" markdown={"开头。\n\n周二把**脚本**写完,重点改了演示。\n\n结尾。"} />);
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());

  act(() => locateNotePassage({ noteId: "n1", text: "周二把**脚本**写完", start: 5 }));

  await waitFor(() => expect(selected()).toBe("周二把脚本写完"));
});

it("请求先到、编辑器后挂:挂上之后照样定位;投给别的笔记的不接", async () => {
  act(() => locateNotePassage({ noteId: "n2", text: "第二篇里的那段", start: 0 }));
  const view = render(<NoteEditor {...props} noteId="n1" markdown={"第一篇。"} />);
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());
  expect(selected()).toBe("");

  view.unmount();
  render(<NoteEditor {...props} noteId="n2" markdown={"开头。\n\n第二篇里的那段话。"} />);
  await waitFor(() => expect(selected()).toBe("第二篇里的那段"));
});

it("那段已经被改掉了:说一声,不乱选", async () => {
  render(<NoteEditor {...props} noteId="n3" markdown={"现在的正文。"} />);
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());
  act(() => locateNotePassage({ noteId: "n3", text: "早就删掉的一句", start: 0 }));
  await waitFor(() => expect(toastMessage).toHaveBeenCalled());
  expect(selected()).toBe("");
});
