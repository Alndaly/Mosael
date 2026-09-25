/**
 * 真的用 Tailwind 把 tokens.css 编一遍,看**生成出来的** CSS 长什么样。
 *
 * vendorStyles / arbitrarySelectors 两道棘轮读的是源码的写法;这里核对写法背后的那件事本身:
 * 第三方样式确实落在 vendor 层、层序确实是那个顺序、工作流皮肤里的选择器确实选得中 React Flow
 * 的真实类名。此前的失效恰恰是"源码看着对、生成的规则不对"—— 只读源码的断言拦不住它。
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { compile } from "tailwindcss";
import { describe, expect, it } from "vitest";

import { CANVAS_EDGE_CLASS } from "@/components/app/canvasEdges";
import { WORKFLOW_CANVAS_CLASS, WORKFLOW_HANDLE_CLASS } from "@/features/workflows/workflowCanvasSkin";

const SRC = join(import.meta.dirname, "..");
const NODE_MODULES = join(SRC, "..", "node_modules");

/** 只认 tokens.css 里真正出现的几种 @import:tailwindcss 自己、tw-animate-css、vendor 表。 */
function resolveStylesheet(id: string, base: string): string {
  if (id.startsWith(".")) return join(base, id);
  if (id === "tailwindcss") return join(NODE_MODULES, "tailwindcss", "index.css");
  if (id === "tw-animate-css") return join(NODE_MODULES, "tw-animate-css", "dist", "tw-animate.css");
  return join(NODE_MODULES, id);
}

async function build(candidates: string[]): Promise<string> {
  const compiler = await compile(readFileSync(join(SRC, "design", "tokens.css"), "utf8"), {
    base: join(SRC, "design"),
    loadStylesheet: async (id, base) => {
      const path = resolveStylesheet(id, base);
      return { path, base: dirname(path), content: readFileSync(path, "utf8") };
    },
    loadModule: async () => {
      throw new Error("tokens.css 没有 @plugin / @config");
    },
  });
  return compiler.build(candidates);
}

/** 所有 `@layer <name> { … }` 块的正文,一块一项。 */
function layerBodies(css: string, name: string): string[] {
  const bodies: string[] = [];
  for (const match of css.matchAll(new RegExp(`@layer ${name}\\s*\\{`, "g"))) {
    let depth = 1;
    let i = match.index! + match[0].length;
    const start = i;
    for (; i < css.length && depth > 0; i += 1) {
      if (css[i] === "{") depth += 1;
      else if (css[i] === "}") depth -= 1;
    }
    bodies.push(css.slice(start, i - 1));
  }
  return bodies;
}

const layerBody = (css: string, name: string) => layerBodies(css, name).join("\n");

const classes = (...lists: string[]) => lists.flatMap((list) => list.split(/\s+/)).filter(Boolean);

describe("编出来的层叠", () => {
  it("层序是 theme → base → vendor → components → utilities,React Flow 的规则全在 vendor 层里", async () => {
    const css = await build([]);
    //: 层序按首次出现排。Tailwind 自己还会在最前面垫一个 `@layer properties;`(@property 的兜底),
    //: 它不和任何人抢属性;要紧的是**第一句提到 theme 的层序声明**就是我们那句 —— Tailwind 自带的
    //: `@layer theme, base, components, utilities;` 排在它后面,已经改不动先后了。
    const orders = [...css.matchAll(/^@layer ([a-z, ]+);$/gm)].map((m) => m[1]).filter((one) => one.includes("theme"));
    expect(orders[0]).toBe("theme, base, vendor, components, utilities");
    const vendor = layerBody(css, "vendor");
    expect(vendor).toContain(".react-flow__edge-path");
    expect(vendor).toContain(".PhotoView-Portal");
    //: vendor 层以外不该再有 React Flow 自己的规则 —— 有的话就是又有一份不分层的漏进来了。
    const outside = layerBodies(css, "vendor").reduce((rest, body) => rest.replace(body, ""), css);
    expect(outside).not.toMatch(/\.react-flow__edge-path\s*\{/);
  }, 20_000);

  it("画布皮肤的每一条都生成了规则,而且选择器里是 React Flow 的真实类名", async () => {
    const candidates = classes(CANVAS_EDGE_CLASS, WORKFLOW_CANVAS_CLASS, WORKFLOW_HANDLE_CLASS);
    const utilities = layerBody(await build(candidates), "utilities");
    for (const name of [
      "react-flow__edge-path",
      "react-flow__edge-text",
      "react-flow__connection-path",
      "react-flow__attribution a",
      "react-flow__edges .react-flow__edge.canvas-edge-taken",
      "react-flow__edge:not(.selected):hover .react-flow__edge-path",
      "canvas-edge-flow .react-flow__edge-path",
      "react-flow__handle-left:hover",
      "react-flow__handle-right:hover",
    ]) {
      expect(utilities, name).toContain(`.${name}`);
    }
    //: 没转义时生成的正是这种"类名里断开一截"的选择器。
    expect(utilities).not.toMatch(/\.react-flow\s+edge/);
    //: 按语义上色的那几条,落到的是 xyflow 读的变量。
    for (const [edge, token] of [
      ["canvas-edge-true", "--success"],
      ["canvas-edge-false", "--destructive"],
      ["canvas-edge-data", "--primary"],
      ["canvas-edge-mismatch", "--warning"],
      ["canvas-edge-taken", "--canvas-edge-run"],
      ["canvas-edge-pending", "--primary"],
    ]) {
      expect(utilities, edge).toMatch(new RegExp(`\\.${edge}[^{]*\\{[^}]*--xy-edge-stroke: var\\(${token}\\)`));
    }
    //: 流动虚线的动画确实生成了(它的 keyframes 在 tokens.css 的 @theme 里),而且只在不要求减少动态时跑。
    expect(utilities).toMatch(/prefers-reduced-motion: no-preference[\s\S]*animation: edge-flow 0\.6s linear infinite/);
  }, 20_000);

  it("加载占位块的扫光:落在 components 层、走 transform、减少动态时只剩底色", async () => {
    //: 带上画板生成中那一格真实挂的工具类:它们得在 utilities 层,才压得过 .skeleton 的默认定位与圆角。
    const css = await build(["absolute", "inset-0", "rounded-lg"]);
    const components = layerBody(css, "components");
    const rule = (selector: string) => {
      const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return components.match(new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
    };
    const host = rule(".skeleton");
    expect(host).toContain("position: relative");
    //: 光要顺着使用方给的圆角被裁掉。
    expect(host).toContain("overflow: hidden");
    expect(host).toContain("background-color: var(--skeleton-base)");
    const sweep = rule(".skeleton::after");
    expect(sweep).toContain("animation: var(--animate-skeleton-shimmer)");
    expect(sweep).toMatch(/linear-gradient\(90deg, transparent 0%, var\(--skeleton-highlight\) 50%, transparent 100%\)/);
    expect(sweep).toContain("transform: translateX(-100%)");
    expect(sweep).toContain("pointer-events: none");
    //: 动画 token 与关键帧确实生成了;平移的是 transform,不是会触发重绘的 background-position。
    expect(css).toMatch(/--animate-skeleton-shimmer: skeleton-shimmer 1\.6s ease-in-out infinite/);
    const keyframes = css.match(/@keyframes skeleton-shimmer\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
    expect(keyframes).toContain("translateX(100%)");
    expect(keyframes).not.toContain("background-position");
    //: 减少动态:扫光整个撤掉,而且这条也在 components 层里 —— 不靠文末那条把时长压成 0.01ms
    //: 的全局兜底(无限循环的动画压短之后是每帧闪一下)。
    expect(components).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.skeleton::after\s*\{[^}]*display: none;[^}]*animation: none;/,
    );
    //: 使用方的工具类在 utilities 层,排在 components 之后。
    const utilities = layerBody(css, "utilities");
    expect(utilities).toMatch(/\.absolute\s*\{\s*position: absolute;/);
  }, 20_000);
});
