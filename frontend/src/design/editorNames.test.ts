/**
 * 可编辑的富文本框(tiptap)要有读屏念得出的名字:`aria-label`,外加 `role="textbox"`、`aria-multiline`。
 *
 * tiptap 渲染的是一个 `contenteditable` 的 div:读屏只念「可编辑文本」,不知道这是提示词、引用模板还是给智能体的话;
 * 它的占位提示(Placeholder 扩展)只是一个 data 属性,读屏不念。笔记正文、评论框写了名字,工作流节点的引用模板、
 * 画板的提示词、智能体的输入框没写 —— 可访问性扫描里,9 个页面唯一没有名字的可交互元素就是 AI Studio 的输入框。
 * 只读的(`editable: false`,笔记预览、评论正文)不算:它们不是输入框。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { SRC, blankComments, tsxSources } from "@/design/jsxSource";

/** 已知的、还没补的。只许减少(ChatComposer 已由智能体那一路补上,清单空了)。 */
const KNOWN = new Set<string>();

/** `useEditor(` 那一次调用的参数原文(按括号配对;注释已经抹掉,字符串里的括号可能让它多吞一点,不影响判断)。 */
function editorCalls(code: string): string[] {
  const calls: string[] = [];
  let from = code.indexOf("useEditor(");
  while (from >= 0) {
    let depth = 0;
    let end = from + "useEditor".length;
    for (; end < code.length; end += 1) {
      if (code[end] === "(") depth += 1;
      else if (code[end] === ")" && --depth === 0) break;
    }
    calls.push(code.slice(from, end + 1));
    from = code.indexOf("useEditor(", end);
  }
  return calls;
}

const editable = (call: string) => !/\beditable:\s*false\b/.test(call);
const named = (call: string) => /["']aria-label["']\s*:/.test(call);

describe("富文本输入框的名字", () => {
  const files = tsxSources().map((rel) => ({ rel, calls: editorCalls(blankComments(readFileSync(join(SRC, rel), "utf8"))) }));

  it("可编辑的 tiptap 都写了 aria-label", () => {
    const offenders = files.filter(({ rel, calls }) => !KNOWN.has(rel) && calls.some((call) => editable(call) && !named(call))).map(({ rel }) => rel);
    expect(offenders, "editorProps.attributes 里补上 aria-label(字段名或占位提示)、role: \"textbox\"、aria-multiline").toEqual([]);
  });

  it("清单里的都还没补 —— 补好了就删掉", () => {
    const fixed = [...KNOWN].filter((rel) => files.find((file) => file.rel === rel)?.calls.every((call) => !editable(call) || named(call)));
    expect(fixed, "已经有名字了 —— 从 KNOWN 里删掉").toEqual([]);
  });

  it("扫得到东西 —— 别变成空转", () => {
    const all = files.flatMap(({ calls }) => calls);
    expect(all.length).toBeGreaterThanOrEqual(6);
    expect(all.some((call) => !editable(call)), "只读的那几处应当被认出来").toBe(true);
    expect(all.filter((call) => editable(call) && named(call)).length).toBeGreaterThanOrEqual(4);
  });
});
