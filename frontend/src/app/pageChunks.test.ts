/**
 * 页面**按需加载**,不许被直接 import 回主包。
 *
 * 此前十四个页面全是静态 import,于是打包出来是一个 4.20 MB 的主包:打开一次素材库,也要先解析
 * 工作流的图编辑器(@xyflow)、笔记的富文本内核(tiptap/prosemirror)、代码高亮(shiki)和图表。
 * 改成 React.lazy 之后主包 0.28 MB,每个页面自己一块。
 *
 * 这条测试拦的是**回头路**:`import { XxxView } from "@/features/…"` 在 pages.tsx 里写一次,
 * 那一页就又回到主包里,而打包仍然成功、测试仍然全绿 —— 只有下次量包体积时才看得出来。
 *
 * 首屏那一页(home)是例外:它一定会被渲染,懒加载只会多一次闪烁。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const PAGES = readFileSync(join(import.meta.dirname, "pages.tsx"), "utf8");

/** 允许静态 import 的:首屏那一页,以及渲染壳自己用的东西。 */
const EAGER = new Set(["@/features/home/HomeView"]);

describe("页面分块", () => {
  it("功能页只能通过 React.lazy 进来", () => {
    const eagerFeatureImports = [...PAGES.matchAll(/^import\s+\{[^}]*\}\s+from\s+"(@\/features\/[^"]+)";/gm)]
      .map((one) => one[1])
      .filter((path) => !EAGER.has(path));
    expect(eagerFeatureImports, "这些页面被静态 import,会回到主包里 —— 改成 React.lazy").toEqual([]);
  });

  it("每个懒加载的页面都拿到了自己的那一块", () => {
    const lazyPages = [...PAGES.matchAll(/React\.lazy\(\(\) => import\("(@\/features\/[^"]+)"\)/g)].map((one) => one[1]);
    expect(lazyPages.length).toBeGreaterThanOrEqual(13);
    expect(new Set(lazyPages).size, "同一个页面被 lazy 了两次").toBe(lazyPages.length);
  });

  it("兜底的 Suspense 在渲染出口上", () => {
    // 每页各写一次的话,漏写的那一页首次打开会直接抛,而不是转一下菊花。
    const app = readFileSync(join(import.meta.dirname, "App.tsx"), "utf8");
    expect(app).toMatch(/<React\.Suspense[\s\S]{0,200}?\{PAGE_RENDERERS\[view\]\(/);
  });
});
