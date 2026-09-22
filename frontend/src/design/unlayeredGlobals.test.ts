/**
 * tokens.css 里给全局兜底的那几条规则,**必须写在 @layer 里面**。
 *
 * Tailwind v4 的工具类都在 `@layer utilities`,而**不分层的 CSS 胜过任何分层 CSS**,
 * 和特异性无关。所以一条不分层的全局规则会把对应的一整族工具类全部压死 —— 而且没有任何
 * 地方会报错:class 还老老实实挂在 DOM 上,只是不算数。
 *
 * 这个项目在同一个坑里栽过三次:
 *
 * 1. `* { border-color }` 不分层 → **全项目的 border-* 颜色类失效**,错误态和选中态画的都是
 *    普通边框。直到有人发现一条本该半透明的分割线是不透明的浅灰。
 * 2. `button, input, select, textarea { font: inherit }` 不分层 → **控件上的字号字重工具类
 *    全部失效**。实测:全站 60 组控件 class 里 40 组声明了字体类,而它们无一例外都渲染成
 *    13px/400 —— 那 40 处写的话没有一句算数。
 * 3. `features/scenes/scenes.css`(1297 行)与 `features/notes/notes.css`(211 行)**整份**
 *    在 @layer 外面 —— 那两个页面上所有同属性的工具类一律不算数。
 *
 * 第三次是这条棘轮**自己放过去的**:它只读 tokens.css。判据一直是对的,扫描面停在写它那天 ——
 * 立棘轮的那个人当时只有一份 CSS 要管。现在它还扫 `features/` 下的每一份 `.css`,
 * 谁新写一份页面样式表都跑不掉。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const SRC = path.resolve(__dirname, "..");
const CSS = fs.readFileSync(path.join(__dirname, "tokens.css"), "utf8");

/**
 * 功能页自己的样式表。
 *
 * **只管 `features/`**:那里的每一份都是某个页面的皮肤,它没有任何理由去压过元素上的工具类。
 * `design/tokens.css` 和 `app/styles.css` 是设计系统自己的全局表 —— 有意不分层的那几条
 * (`:root` 上的变量、滚动条伪元素、玻璃外观的根级开关)住在那里,由上面那两条点名检查
 * 各自盯着;把它们和功能页混成一条规则,只会逼人去写一份长长的豁免名单。
 */
function featureStylesheets(): Array<[string, string]> {
  const found: Array<[string, string]> = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".css")) found.push([path.relative(SRC, full), fs.readFileSync(full, "utf8")]);
    }
  };
  walk(path.join(SRC, "features"));
  return found.sort();
}

/** 这份表里**没有**写在 @layer 里的顶层规则(选择器片段,截断到 80 字)。 */
function unlayeredRules(css: string): string[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/@layer[^{;]*;/g, "");
  const offenders: string[] = [];
  let depth = 0;
  //: 顶层规则的选择器从**上一次深度归零**处开始。按"上一个 `}`"去切会在嵌套块之后切出
  //: 一段残片 —— 第一版就是这么误报的。
  let headFrom = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "{") {
      if (depth === 0) {
        const head = text.slice(headFrom, i).trim();
        // @layer 自己,以及不与工具类竞争的 at-rule(关键帧、字体、属性声明)放行。
        if (!/^@(layer|keyframes|font-face|property|supports|charset|import)\b/.test(head)) {
          offenders.push(head.split("\n").pop()!.trim().slice(0, 80));
        }
      }
      depth += 1;
    } else if (text[i] === "}") {
      depth -= 1;
      if (depth === 0) headFrom = i + 1;
    }
  }
  return offenders;
}

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

describe("功能页的样式表", () => {
  it("扫描面自己长 —— features/ 下的每一份 .css 都在名单里", () => {
    // 这条先站住:走空目录的话,下面那条断言天然成立。
    const all = featureStylesheets();
    expect(all.length).toBeGreaterThanOrEqual(3);
    expect(all.map(([name]) => name)).toContain("features/scenes/scenes.css");
  });

  it.each(featureStylesheets())("%s 整份写在 @layer 里面", (name, css) => {
    expect(
      unlayeredRules(css),
      `${name}:这些规则在 @layer 外面 —— 它们会压过这个页面上所有同属性的工具类,` +
        "而 class 仍然挂在 DOM 上,没有任何地方会报错。整份包进 @layer components 即可。",
    ).toEqual([]);
  });
});
