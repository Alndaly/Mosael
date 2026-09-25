/**
 * 画布节点(React Flow 的 nodeTypes)里的输入框不直接绑节点数据,走草稿框。
 *
 * 节点里读到的数据是 React Flow **在 effect 里**才抄进它 store 的那份 —— 比 onChange 慢一拍。
 * `<textarea value={item.text} onChange=…>` 于是每敲一下都被 React 先写回旧字:英文看不出来,
 * 拼音组词被打断、字母直接上屏(便签里敲出「daa skx」)。节点里的框一律用
 * components/ui/draft-text 的 DraftTextarea / DraftInput / useDraftText。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.") ? [full] : [];
  });
}

const stripComments = (code: string): string =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");

/** 一个受控的原生框:`<textarea|input|Textarea|Input` 起头、到 `>` 之前带着 `value=`。 */
const CONTROLLED_FIELD = /<(textarea|input|Textarea|Input)\b[^>]*?\bvalue=\{/s;

describe("画布节点里的输入框", () => {
  it("节点组件所在的文件里没有直接受控于节点数据的原生框", () => {
    const nodeFiles = sourceFiles(SRC).filter((file) => /\bNodeProps\b/.test(readFileSync(file, "utf8")));
    expect(nodeFiles.length).toBeGreaterThan(0);
    const offenders = nodeFiles.filter((file) => CONTROLLED_FIELD.test(stripComments(readFileSync(file, "utf8"))));
    expect(offenders.map((file) => file.slice(SRC.length + 1))).toEqual([]);
  });
});
