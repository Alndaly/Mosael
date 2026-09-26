/**
 * CodeMirror 的样式是运行时注入的、不在任何 CSS layer 里;Tailwind 的 utility 在 @layer utilities 里。
 * 没进 layer 的样式不看特异性就赢 —— 所以改 CodeMirror **自己也设了**的那几样(底色、聚焦描边、
 * 行号槽的边框),类名不带 `!` 就等于没写。聚焦时那圈多余的虚线(`outline: 1px dotted`)就是
 * `outline-none` 少了一个 `!` 漏出来的,jsdom 里看不出来。
 */
import fs from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

const SOURCE = fs.readFileSync(path.join(__dirname, "code-editor.tsx"), "utf8");
/** CodeMirror 的基础 / 明暗主题里设过的属性:改它们必须 `!`。 */
const CONTESTED = /^(bg-|outline-|border-)/;

it("overrides of properties CodeMirror styles itself are !important", () => {
  const overrides = [...SOURCE.matchAll(/\[&_\.cm-[^\]]+\]:([^\s"]+)/g)].map((match) => match[0]);
  const contested = overrides.filter((cls) => CONTESTED.test(cls.slice(cls.indexOf("]:") + 2)));
  expect(contested.length).toBeGreaterThan(0);
  expect(contested.filter((cls) => !cls.endsWith("!"))).toEqual([]);
});
