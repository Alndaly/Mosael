/**
 * 第三方组件的样式表**必须进主包**,不能跟着某一页走。
 *
 * 踩过的那次:React Flow 的 `style.css` 只在 `WorkflowsView` 里 import,而两个画布都用它
 * (工作流、无限画布)。页面改成按需加载之后(`pageChunks.test.ts` 那次优化),没进过工作流页
 * 就永远不会加载这份样式 —— 直接打开无限画布时,整个画布没有 React Flow 的样式:pane 不成形、
 * 拖不动也点不了,右下角那行 "React Flow" 因为失去绝对定位跑到了左上角。
 *
 * **而它表现成"有时候"**:这次有没有先进过工作流页是随机的。构建成功、类型全绿、测试全绿,
 * 只有真的按那个顺序点一遍才会遇到 —— 正因为如此,这里立一道。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
const ENTRY = join(SRC, "app", "main.tsx");

/** 被多个页面共用、因此不能长在任何一页里的第三方样式表。 */
const SHARED_VENDOR_CSS = ["@xyflow/react/dist/style.css"];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (entry === "node_modules") return [];
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

describe("第三方样式表", () => {
  it.each(SHARED_VENDOR_CSS)("%s 在应用入口里加载", (css) => {
    expect(readFileSync(ENTRY, "utf8")).toContain(css);
  });

  it.each(SHARED_VENDOR_CSS)("%s 不长在任何一页里", (css) => {
    const offenders = sources(SRC)
      .filter((path) => path !== ENTRY)
      .filter((path) => readFileSync(path, "utf8").includes(css))
      .map((path) => path.slice(SRC.length + 1));
    expect(
      offenders,
      "按需加载之后,只有进过那一页才会加载这份样式 —— 另一页就没有样式,而构建和测试都不会红",
    ).toEqual([]);
  });
});
