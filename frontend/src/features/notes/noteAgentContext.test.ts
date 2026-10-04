/**
 * 笔记页助手每条消息附带的那段隐藏上下文:说清是哪一篇、正文(短的整篇,长的只给开头并说怎么分段读)、
 * 选中的那段或者光标在哪。总长要守住 —— 和附件、引用的笔记共用一条 4000 字的上限。
 */
import { expect, it } from "vitest";
import { messages, type MessageKey } from "@/app/messages";
import { NOTE_AGENT_CONTEXT_BUDGET, noteAgentContext } from "./noteAgentContext";

const t = (key: MessageKey) => messages["zh-CN"][key];
const note = { id: "n1", title: "周报", revision: 3, markdown: "周一开了会。\n\n周二写了脚本。" };

it("短的笔记:标题、id、版本和整篇正文都在,并点名用 edit_note 改", () => {
  const context = noteAgentContext(t, note, null);
  expect(context).toContain("「周报」");
  expect(context).toContain("note_id=n1");
  expect(context).toContain("第 3 版");
  expect(context).toContain("周二写了脚本。");
  expect(context).toContain("edit_note");
});

it("长的笔记:只给开头,说清用 read_note 分段读,不把整篇塞进来", () => {
  const long = { ...note, markdown: `开头那句。${"中间的字".repeat(2000)}结尾那句。` };
  const context = noteAgentContext(t, long, null);
  expect(context).toContain("开头那句。");
  expect(context).not.toContain("结尾那句。");
  expect(context).toContain("read_note");
  expect(context.length).toBeLessThanOrEqual(NOTE_AGENT_CONTEXT_BUDGET);
});

it("选中了一段:原文和位置都在", () => {
  const context = noteAgentContext(t, note, { text: "周二写了脚本", start: 8, end: 14, before: "会。\n\n", after: "。" });
  expect(context).toContain("用户选中了这一段");
  expect(context).toContain("周二写了脚本");
  expect(context).toContain("第 8–14 字");
});

it("选中的一段很长:只给头尾和位置,说清用 read_note 读全", () => {
  const body = `选区开头${"很长".repeat(1500)}选区结尾`;
  const long = { ...note, markdown: body };
  const context = noteAgentContext(t, long, { text: body, start: 0, end: body.length, before: "", after: "" });
  expect(context).toContain("选区开头");
  expect(context).toContain("选区结尾");
  expect(context).toContain(`length=${body.length}`);
  expect(context.length).toBeLessThanOrEqual(NOTE_AGENT_CONTEXT_BUDGET);
});

it("选区在正文里对不上(编辑器纯文字):如实说,让它先读原文", () => {
  const context = noteAgentContext(t, note, { text: "别处的字", start: -1, end: -1, before: "", after: "" });
  expect(context).toContain("可能和正文原文不逐字一致");
});

it("只有光标:给前后文当插入锚点", () => {
  const context = noteAgentContext(t, note, { text: "", start: 6, end: 6, before: "周一开了会。", after: "\n\n周二" });
  expect(context).toContain("前文「周一开了会。」");
  expect(context).toContain("after 锚点");
});

it("没打开笔记:说清在笔记页、怎么找", () => {
  const context = noteAgentContext(t, null, null);
  expect(context).toContain("没有打开笔记");
  expect(context).toContain("search_notes");
});
