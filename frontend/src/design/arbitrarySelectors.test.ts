/**
 * Tailwind 任意选择器里的 BEM 类名,`__` 必须写成 `\_\_`。
 *
 * Tailwind 把任意值里的 `_` 一律换成空格。于是 `[&_.react-flow__edge-path]:stroke-success` 生成的
 * 是 `.x .react-flow  edge-path { … }` —— 一个选不中任何东西的后代选择器。**类名挂在 DOM 上、规则也
 * 生成了、构建和测试全绿**,只有盯着画面才看得出:工作流里真/假分支的红绿、数据线的主色和线宽、
 * 接点的悬停放大、大图预览的顶栏和计数,全是这么"写了等于没写"的。
 *
 * 写法:整串用 String.raw,选择器里写 `\_\_`(普通字符串里的 `\_` 会被 JS 吃掉反斜杠,运行时的
 * 类名就和生成的规则对不上)。`_` 单独出现仍然是"这里要一个空格",比如 `[&_.x]` 的后代组合符。
 *
 * 判据只看**变体位置**的方括号(`[…]:` 紧跟冒号):那里放的是选择器。值位置的方括号
 * (`bg-[…]`、`[stroke-dasharray:6_5]`)里的下划线本来就是空格,不归这条管。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (entry === "node_modules") return [];
    //: 生成的 API 类型里满是 `users__user_id__avatar` 这种操作名,和样式无关。
    if (path === join(SRC, "api", "generated")) return [];
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

/** 源码里所有变体位置的任意选择器(`[…]` 后面紧跟 `:`),连同所在文件。 */
function arbitraryVariants(): Array<[string, string]> {
  return sources(SRC).flatMap((path) =>
    [...readFileSync(path, "utf8").matchAll(/\[([^[\]\s"'`]*)\](?=:)/g)].map(
      (match) => [path.slice(SRC.length + 1), match[1]] as [string, string],
    ),
  );
}

/** 和 Tailwind 一样的判读:转义过的 `\_` 先换成占位,剩下的下划线只要挨着另一个下划线
 *  (不管那个转没转义)就是一处被拆开的类名 —— `__` 和只转义一半的 `\__` 都算。 */
const hasUnescapedDoubleUnderscore = (selector: string) => /_[_¤]|¤_/.test(selector.replace(/\\_/g, "¤"));

describe("任意选择器里的双下划线", () => {
  it("判据本身:`\\_\\_` 放行,`__` 与只转义一半的 `\\__` 拦下", () => {
    expect(hasUnescapedDoubleUnderscore(String.raw`&_.react-flow\_\_edge-path`)).toBe(false);
    expect(hasUnescapedDoubleUnderscore("&_.react-flow__edge-path")).toBe(true);
    expect(hasUnescapedDoubleUnderscore(String.raw`&_.react-flow\__edge-path`)).toBe(true);
    expect(hasUnescapedDoubleUnderscore("&_.wf-edge-true")).toBe(false);
  });

  it("扫描面站得住 —— 确实扫到了那些写 React Flow 内部类名的选择器", () => {
    // 走空的话下面那条断言天然成立;这里点名两处已知的使用者。
    const found = arbitraryVariants();
    expect(found.some(([file, sel]) => file.endsWith("workflowCanvasSkin.ts") && sel.includes("react-flow"))).toBe(true);
    expect(found.some(([file, sel]) => file.endsWith("image-preview.tsx") && sel.includes("PhotoView-Slider"))).toBe(true);
  });

  it("没有一处写着没转义的 `__`", () => {
    const offenders = arbitraryVariants()
      .filter(([, selector]) => hasUnescapedDoubleUnderscore(selector))
      .map(([file, selector]) => `${file}: [${selector}]`);
    expect(
      offenders,
      "Tailwind 会把这些 `__` 换成两个空格,规则选不中任何东西 —— 改成 `\\_\\_` 并用 String.raw 包住整串",
    ).toEqual([]);
  });
});
