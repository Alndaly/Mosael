/**
 * 行内 markdown 的规则在两个包里各有一份:官网 `website/src/lib/inline-markdown.ts` 和这里的
 * `inlineSyntax.ts`(两个包不共享源码)。解析那一段必须**逐字相同** —— 同一句插件说明,
 * 官网和应用里认出来的粗体、代码、链接不能不一样。改一边的时候把另一边一起改。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "../../../..");

function parserOf(file: string, end: string): string {
  const code = readFileSync(join(ROOT, file), "utf8");
  const from = code.indexOf("export type InlineNode");
  const to = code.indexOf(end, from);
  expect(from, `${file} 里找不到 InlineNode`).toBeGreaterThan(-1);
  expect(to, `${file} 里找不到解析段的结尾`).toBeGreaterThan(from);
  return code.slice(from, to).trim();
}

it("官网和应用的解析器逐字相同", () => {
  const website = parserOf("website/src/lib/inline-markdown.ts", "/** 按**看得见的字数**截断");
  const app = parserOf("frontend/src/components/markdown/inlineSyntax.ts", "function textOf");
  expect(app).toBe(website);
});
