/** @vitest-environment jsdom */
/**
 * 笔记里的高亮:存成 `==文字==`(Obsidian / Typora 也认这一种),编辑、阅读、Markdown 三种模式之间来回不丢不变。
 * 一种颜色 —— 多色要先定存储格式(`==` 没有地方放颜色),一种颜色够用就不加这层复杂度。
 */
import { Editor } from "@tiptap/react";
import { afterEach, expect, it } from "vitest";
import { noteExtensions } from "./editorExtensions";
import { HIGHLIGHT } from "./NoteHighlight";
import { noteSnippet } from "./noteSnippet";
import { plainExcerpt } from "@/lib/plainExcerpt";

const editors: Editor[] = [];
afterEach(() => { while (editors.length) editors.pop()!.destroy(); });
const open = (content: string | object, readonly = false) => {
  const editor = new Editor({ extensions: noteExtensions(readonly), content, ...(typeof content === "string" ? { contentType: "markdown" as const } : {}) });
  editors.push(editor);
  return editor;
};

it("==文字== 读进来是高亮(里面还能套粗体),存回去一字不差", () => {
  const markdown = "开场 ==三十秒太慢,**必须**压到十五秒== 以内。";
  const editor = open(markdown);
  const mark = editor.view.dom.querySelector("mark");
  expect(mark?.textContent).toBe("三十秒太慢,必须压到十五秒");
  expect(mark?.querySelector("strong")?.textContent).toBe("必须");
  expect(editor.getMarkdown().trim()).toBe(markdown);
  //: 再读一遍还是同一份文档。
  expect(open(editor.getMarkdown()).getJSON()).toEqual(editor.getJSON());
});

it("只读的渲染(版本记录预览、画板上的文档格)同样画出高亮", () => {
  const reader = open("==要点==", true);
  expect(reader.view.dom.querySelector("mark")?.textContent).toBe("要点");
});

it("正文里本来就是字面的 ==x== 存回去时转义,再读不会凭空变成高亮", () => {
  const editor = open({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "a==b==c 和 x == y" }] }] });
  const saved = editor.getMarkdown();
  const reopened = open(saved);
  expect(reopened.view.dom.querySelector("mark")).toBeNull();
  expect(reopened.getText()).toBe("a==b==c 和 x == y");
});

it("切换高亮:没高亮的加上,已高亮的取消", () => {
  const editor = open("一段要标的字");
  editor.commands.setTextSelection({ from: 1, to: 3 });
  editor.commands.toggleMark(HIGHLIGHT);
  expect(editor.getMarkdown().trim()).toBe("==一段==要标的字");
  editor.commands.toggleMark(HIGHLIGHT);
  expect(editor.getMarkdown().trim()).toBe("一段要标的字");
});

it("一行摘要、小条上的摘录都去掉 == 记号", () => {
  expect(noteSnippet("开场 ==三十秒太慢== 以内")).toBe("开场 三十秒太慢 以内");
  expect(plainExcerpt("==三十秒太慢==")).toBe("三十秒太慢");
});
