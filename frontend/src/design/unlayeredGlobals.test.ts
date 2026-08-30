/**
 * tokens.css 里给全局兜底的那几条规则,**必须写在 @layer 里面**。
 *
 * Tailwind v4 的工具类都在 `@layer utilities`,而**不分层的 CSS 胜过任何分层 CSS**,
 * 和特异性无关。所以一条不分层的全局规则会把对应的一整族工具类全部压死 —— 而且没有任何
 * 地方会报错:class 还老老实实挂在 DOM 上,只是不算数。
 *
 * 这个项目在同一个坑里栽过两次:
 *
 * 1. `* { border-color }` 不分层 → **全项目的 border-* 颜色类失效**,错误态和选中态画的都是
 *    普通边框。直到有人发现一条本该半透明的分割线是不透明的浅灰。
 * 2. `button, input, select, textarea { font: inherit }` 不分层 → **控件上的字号字重工具类
 *    全部失效**。实测:全站 60 组控件 class 里 40 组声明了字体类,而它们无一例外都渲染成
 *    13px/400 —— 那 40 处写的话没有一句算数。
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

describe("控件字体继承", () => {
  it("不能写在 @layer 外面 —— 那会压过控件上所有 text-* / font-* 工具类", () => {
    const found = [...CSS.matchAll(/font:\s*inherit/g)];
    expect(found.length, "找不到那条控件字体继承了 —— 改写法了?").toBeGreaterThan(0);
    for (const one of found) {
      expect(
        depthAt(CSS, one.index!),
        "它跑到 @layer 外面了 —— 按钮和输入框上的字号字重会全部失效",
      ).toBeGreaterThanOrEqual(2);
    }
  });
});

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
