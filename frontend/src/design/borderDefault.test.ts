/**
 * 全局那条 `* { border-color: … }` 是**默认值**,不是强制值。
 *
 * 它一旦不分层,就会压过 Tailwind 的所有工具类(v4 里工具类都在 @layer utilities,而不分层的
 * CSS 胜过任何分层 CSS,和特异性无关)。后果是**全项目的 border-* 颜色类全部失效**:
 * 输入框的错误态画的是普通边框、选中态画的是普通边框,而没有任何地方会报错 —— 这条 bug
 * 在这个项目里活了很久,直到有人发现一条本该半透明的分割线是不透明的浅灰。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const CSS = fs.readFileSync(path.join(__dirname, "tokens.css"), "utf8");

/** 这个声明所在的嵌套深度:往前数没配对的 `{`。
 *  在 `@layer base { * { … } }` 里是 2;裸写 `* { … }` 是 1。 */
function depthAt(css: string, index: number): number {
  let depth = 0;
  for (let i = 0; i < index; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") depth -= 1;
  }
  return depth;
}

describe("全局边框默认色", () => {
  it("不能写在 @layer 外面 —— 那会压过所有 border-* 工具类", () => {
    const found = [...CSS.matchAll(/border-color:\s*var\(--border\)/g)];
    expect(found.length, "找不到那条全局默认边框色了 —— 改名了?").toBeGreaterThan(0);
    for (const one of found) {
      //: 裸写在 `* { }` 里是深度 1;包进 `@layer base { }` 之后是 2。
      expect(depthAt(CSS, one.index!), "它跑到 @layer 外面了 —— 会压过所有 border-* 工具类").toBeGreaterThanOrEqual(2);
    }
  });
});
