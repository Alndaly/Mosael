/**
 * 第三方组件的样式表**必须进主包**,而且**必须进 vendor 层**。
 *
 * 进主包 —— 踩过的那次:React Flow 的 `style.css` 只在 `WorkflowsView` 里 import,而两个画布都用它
 * (工作流、无限画布)。页面改成按需加载之后(`pageChunks.test.ts` 那次优化),没进过工作流页
 * 就永远不会加载这份样式 —— 直接打开无限画布时,整个画布没有 React Flow 的样式:pane 不成形、
 * 拖不动也点不了,右下角那行 "React Flow" 因为失去绝对定位跑到了左上角。
 * **而它表现成"有时候"**:这次有没有先进过工作流页是随机的。构建成功、类型全绿、测试全绿,
 * 只有真的按那个顺序点一遍才会遇到。
 *
 * 进 vendor 层 —— 同一份表在 JS 里 import 时不在任何 @layer 里,而不分层的声明无视选择器权重、
 * 压过 Tailwind 的 `@layer utilities`。于是工作流里真/假分支的红绿、数据线的主色和线宽写了几个月,
 * 一条都没生效;大图预览为了压过 react-photo-view,每个类都挂着 `!`。
 * 现在它们在 tokens.css 里 `@import … layer(vendor)`,vendor 排在 base 之后、utilities 之前。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
const ENTRY = join(SRC, "app", "main.tsx");
const TOKENS = join(SRC, "design", "tokens.css");
const NODE_MODULES = join(SRC, "..", "node_modules");

/** 带规则的第三方样式表:都要经 tokens.css 进 vendor 层。 */
const VENDOR_CSS = ["@xyflow/react/dist/style.css", "react-photo-view/dist/react-photo-view.css"];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (entry === "node_modules") return [];
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** 去掉注释之后的第一条语句(到第一个 `;` 或 `{`)。 */
function firstStatement(css: string): string {
  const text = stripComments(css).trim();
  return text.slice(0, text.search(/[;{]/) + 1).replace(/\s+/g, " ");
}

/** JS/TS 里 `import "x.css"` 的裸模块名(相对路径和 `@/` 别名是我们自己的表,不算)。 */
function bareCssImports(source: string): string[] {
  return [...source.matchAll(/^\s*import\s+["']([^"'.@/][^"']*|@(?!\/)[^"']*)\.css["'];?/gm)].map((m) => `${m[1]}.css`);
}

describe("第三方样式表", () => {
  it("层序在 tokens.css 第一句说定:vendor 在 base 之后、components/utilities 之前", () => {
    expect(firstStatement(readFileSync(TOKENS, "utf8"))).toBe("@layer theme, base, vendor, components, utilities;");
  });

  it("应用入口加载 tokens.css —— vendor 层就是从这里进主包的", () => {
    expect(readFileSync(ENTRY, "utf8")).toContain('import "@/design/tokens.css";');
  });

  it.each(VENDOR_CSS)("%s 在 tokens.css 里以 layer(vendor) 引入", (css) => {
    expect(stripComments(readFileSync(TOKENS, "utf8"))).toContain(`@import "${css}" layer(vendor);`);
  });

  it.each(VENDOR_CSS)("%s 不在任何 JS/TS 里 import(那样不分层,也可能只跟着某一页走)", (css) => {
    const offenders = sources(SRC)
      .filter((path) => readFileSync(path, "utf8").includes(css))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, "在 JS 里 import 的 CSS 不分层,会压过这张表上所有同属性的工具类").toEqual([]);
  });

  it("JS/TS 里 import 的第三方 CSS 只能是纯字体声明(@font-face 不和工具类抢任何属性)", () => {
    const found = sources(SRC).flatMap((path) => bareCssImports(readFileSync(path, "utf8")).map((css) => [path, css] as const));
    // 先站住:入口里那份霞鹜文楷就是一份,扫描走空的话下面那条断言天然成立。
    expect(found.map(([, css]) => css)).toContain("lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css");
    for (const [path, css] of found) {
      const rest = stripComments(readFileSync(join(NODE_MODULES, css), "utf8")).replace(/@font-face\s*\{[^}]*\}/g, "");
      expect(
        rest.includes("{"),
        `${path.slice(SRC.length + 1)} 在 JS 里 import 了 ${css},而它不只是字体声明 —— 它不分层,会压过工具类。` +
          "改到 design/tokens.css 里 `@import … layer(vendor)`,并登记到这里的 VENDOR_CSS。",
      ).toBe(false);
    }
  });
});
