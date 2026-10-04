/** @vitest-environment jsdom */
/**
 * 笔记页给助手的两样东西:
 * - 选区 / 光标在**正文 Markdown** 里是哪一段 —— 助手要拿它当 edit_note 的锚点,所以必须逐字是存下来的那份原文
 *   (带着 `**` 这些标记),而不是编辑器里看到的纯文字;
 * - 服务端改了一段之后,编辑器按**最小差异**接过来 —— 只动改了的那一段、光标不跳,而且进撤销历史。
 */
import { Editor } from "@tiptap/react";
import { afterEach, expect, it } from "vitest";
import { noteExtensions } from "./editorExtensions";
import { findPassage, followMarkdown, readNoteSelection, SELECTION_CONTEXT_CHARS } from "./noteSelection";

const editors: Editor[] = [];
afterEach(() => { while (editors.length) editors.pop()!.destroy(); });

function open(markdown: string) {
  const editor = new Editor({ extensions: noteExtensions(), content: markdown, contentType: "markdown" });
  editors.push(editor);
  return editor;
}

/** 文档里第 n 次出现这段纯文字的起止位置(ProseMirror 坐标)。 */
function rangeOf(editor: Editor, text: string): { from: number; to: number } {
  let found: { from: number; to: number } | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (found || !node.isText) return;
    const at = node.text!.indexOf(text);
    if (at >= 0) found = { from: pos + at, to: pos + at + text.length };
  });
  if (!found) throw new Error(`not found: ${text}`);
  return found;
}

it("选中带格式的一段:给出的是正文 Markdown 里逐字的原文和它的位置", () => {
  const editor = open("# 周报\n\n周一和**剪辑组**对了节奏。\n\n周二写了脚本。");
  const markdown = editor.getMarkdown();
  const { from } = rangeOf(editor, "周一和");
  const { to } = rangeOf(editor, "对了节奏");
  editor.commands.setTextSelection({ from, to });

  const selection = readNoteSelection(editor)!;

  expect(selection.text).toBe("周一和**剪辑组**对了节奏");
  expect(markdown.slice(selection.start, selection.end)).toBe(selection.text);
  expect(selection.before.endsWith("# 周报\n\n")).toBe(true);
  expect(selection.after.startsWith("。")).toBe(true);
});

it("只是一个光标:原文为空,前后文是光标两边的 Markdown(插入时当锚点)", () => {
  const editor = open("第一段。\n\n第二段写到一半");
  const { to } = rangeOf(editor, "第二段");
  editor.commands.setTextSelection(to);

  const selection = readNoteSelection(editor)!;

  expect(selection.text).toBe("");
  expect(selection.start).toBe(selection.end);
  expect(selection.before).toBe("第一段。\n\n第二段");
  expect(selection.after).toBe("写到一半");
});

it("前后文各取有限的长度,不把整篇塞进去", () => {
  const long = "字".repeat(SELECTION_CONTEXT_CHARS * 3);
  const editor = open(`${long}中间${long}`);
  const { from, to } = rangeOf(editor, "中间");
  editor.commands.setTextSelection({ from, to });

  const selection = readNoteSelection(editor)!;

  expect(selection.text).toBe("中间");
  expect(selection.before.length).toBe(SELECTION_CONTEXT_CHARS);
  expect(selection.after.length).toBe(SELECTION_CONTEXT_CHARS);
});

it("服务端改了中间一段:只换那一段、光标留在原处,撤销一步回到改之前", () => {
  const editor = open("开头不动。\n\n要改的一段。\n\n结尾也不动。");
  const caret = rangeOf(editor, "结尾").to;
  editor.commands.setTextSelection(caret);
  const before = editor.getJSON();

  const changed = followMarkdown(editor, "开头不动。\n\n改好的一段,长了一些。\n\n结尾也不动。");

  expect(changed).toBe(true);
  expect(editor.getText()).toContain("改好的一段,长了一些。");
  //: 光标跟着映射:还在「结尾」后面,而不是跳到开头或末尾。
  expect(editor.state.doc.textBetween(editor.state.selection.from - 2, editor.state.selection.from)).toBe("结尾");
  expect(editor.can().undo()).toBe(true);
  editor.commands.undo();
  expect(editor.getJSON()).toEqual(before);
});

it("改了相隔的两处:中间没动的那段原样留着,选在那里的选区也不被撑大", () => {
  const editor = open("甲段改前。\n\n中间不动的一段。\n\n乙段改前。\n\n- 一\n- 二");
  editor.commands.setTextSelection(rangeOf(editor, "不动"));

  followMarkdown(editor, "甲段改好了。\n\n中间不动的一段。\n\n乙段改前。\n\n- 一\n- 二\n- 三");

  const { from, to } = editor.state.selection;
  expect(editor.state.doc.textBetween(from, to)).toBe("不动");
  expect(editor.getText()).toContain("甲段改好了。");
  expect(editor.getText()).toContain("三");
  //: 仍然是**一步**撤销:智能体那一次改动是一件事。
  editor.commands.undo();
  expect(editor.getText()).toContain("甲段改前。");
  expect(editor.getText()).not.toContain("三");
});

it("一样的正文不产生任何改动(也不进撤销历史)", () => {
  const editor = open("没变。");
  expect(followMarkdown(editor, editor.getMarkdown())).toBe(false);
  expect(editor.can().undo()).toBe(false);
});

it("按选区原文找回那一段(带着 Markdown 记号也认),同一段字出现多次时挑离原位置最近的那处", () => {
  const editor = open("开头一句。\n\n周二把**脚本**写完。\n\n中间。\n\n周二把**脚本**写完。");
  const markdown = editor.getMarkdown();
  const second = markdown.lastIndexOf("周二把**脚本**写完");

  const range = findPassage(editor, "周二把**脚本**写完", second)!;

  expect(editor.state.doc.textBetween(range.from, range.to)).toBe("周二把脚本写完");
  //: 挑的是后面那处(位置离第二处近),不是第一处。
  expect(range.from).toBeGreaterThan(rangeOf(editor, "中间").from);
  expect(findPassage(editor, "正文里没有的一句", 0)).toBeNull();
});
