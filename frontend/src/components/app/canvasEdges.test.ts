/**
 * 棘轮:**画布连线长什么样,只在 components/app/canvasEdges 一处说。**
 *
 * 此前连线的样子散在五处(画板吃 xyflow 默认值、工作流皮肤按语义另写、分支箭头在模型里单造、
 * 运行走过的线在视图里写行内 style、待定的线和拖线途中那根各一份),线宽 1.5 / 2 / 2.2 / 2.4 / 2.6
 * 五个数、箭头大小两种、同一个「选中」在一种线上变主色在另一种线上不变。**没有一处报错** ——
 * 每一处单看都对,合起来是五套。
 *
 * 判据(扫 `src/` 下的源码,先剥注释,测试文件和 canvasEdges.ts 本身除外):
 *  · 不写 React Flow 连线的变量(`--xy-edge-*`、`--xy-connectionline-*`),不选连线的内部类名
 *    (`.react-flow__edge*`、`__connection*`、`__arrowhead`)。
 *  · 不造箭头(`MarkerType`),`markerEnd` / `markerStart` 除了 `undefined`(「这根不要箭头」)
 *    不给别的值 —— 要箭头就带 `CANVAS_EDGE_OPTIONS`。
 *  · 不给拖线途中那根传 `connectionLineStyle`,不用 React Flow 自己那套 `animated` 虚线。
 *  · 画布源码(import 了 @xyflow/react 的文件)里不写 `stroke` / `strokeWidth` / `strokeDasharray`。
 *  · 变体类名(`canvas-edge-*`)不手写,经 `canvasEdgeClass()` 取。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { MarkerType } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  CANVAS_EDGE_CLASS,
  CANVAS_EDGE_MARKER,
  CANVAS_EDGE_OPTIONS,
  CANVAS_EDGE_WIDTH,
  CANVAS_PREVIEW_EDGE,
  canvasEdgeClass,
  type CanvasEdgeTone,
} from "@/components/app/canvasEdges";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..", "..");
const HOME = join("components", "app", "canvasEdges.ts");

/** 会被执行的那部分源码 —— 行注释和块注释都剥掉(解释改动的注释里正好会引用被禁的写法)。 */
function executable(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "generated" ? [] : sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

const RULES: Array<[string, RegExp, (code: string) => boolean]> = [
  ["写了 React Flow 连线的 CSS 变量", /--xy-(edge|connectionline)-/, () => true],
  ["选了 React Flow 连线的内部类名", /react-flow(\\_\\_|__)(edge|connection|arrowhead)/, () => true],
  ["自己造箭头", /\bMarkerType\b/, () => true],
  ["给了箭头(要箭头就带 CANVAS_EDGE_OPTIONS)", /\bmarker(End|Start)\s*:\s*(?![\s]|undefined\b)/, () => true],
  ["给拖线途中那根传了样式", /\bconnectionLineStyle\b/, () => true],
  ["用了 React Flow 自己的 animated 虚线", /\banimated\s*:\s*true\b/, (code) => code.includes("@xyflow/react")],
  ["在画布源码里写了描边", /\bstroke(Width|Dasharray|Opacity)?\s*:/, (code) => code.includes("@xyflow/react")],
  ["手写了变体类名(经 canvasEdgeClass 取)", /["'`\s]canvas-edge-[a-z]/, () => true],
];

describe("连线的外观只在一处", () => {
  it("扫描面站得住 —— 确实扫到了两块画布和那张缩略图", () => {
    //: 走空目录的话,下面那条断言天然成立。
    const files = sources(SRC).map((path) => path.slice(SRC.length + 1));
    expect(files.length).toBeGreaterThan(300);
    for (const one of ["features/boards/BoardCanvas.tsx", "features/workflows/WorkflowsView.tsx", "components/app/canvasPendingLink.tsx", HOME]) {
      expect(files, one).toContain(one);
    }
  });

  it("判据本身拦得住此前那几种写法", () => {
    const hit = (code: string) => RULES.filter(([, pattern, applies]) => applies(code) && pattern.test(code)).map(([why]) => why);
    expect(hit(`style: { stroke: "var(--success)", strokeWidth: 2.4 } // "@xyflow/react"`)).toContain("在画布源码里写了描边");
    expect(hit(`markerEnd: { ...CANVAS_EDGE_MARKER, color: branchColor }`)).toContain("给了箭头(要箭头就带 CANVAS_EDGE_OPTIONS)");
    expect(hit(`markerEnd: undefined`)).toEqual([]);
    expect(hit(String.raw`"[&_.wf-edge-data]:[--xy-edge-stroke-width:2]"`)).toContain("写了 React Flow 连线的 CSS 变量");
    expect(hit(String.raw`[&_.react-flow\_\_edge-path]:[stroke-linecap:round]`)).toContain("选了 React Flow 连线的内部类名");
    expect(hit(`className: "canvas-edge-true"`)).toContain("手写了变体类名(经 canvasEdgeClass 取)");
    expect(hit(`import { CANVAS_EDGE_CLASS } from "@/components/app/canvasEdges"`)).toEqual([]);
  });

  it("别处不写线色、线宽、箭头、虚线", () => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      const where = path.slice(SRC.length + 1);
      if (where === HOME) continue;
      const code = executable(readFileSync(path, "utf8"));
      for (const [why, pattern, applies] of RULES) {
        if (applies(code) && pattern.test(code)) offenders.push(`${where} → ${why}`);
      }
    }
    expect(offenders, "把它收进 components/app/canvasEdges(那张变体表),调用处只挂它给的类和选项。").toEqual([]);
  });

  it("列表卡片的缩略图也用同一个线色", () => {
    const preview = readFileSync(join(SRC, "components", "layout", "CanvasPreview.tsx"), "utf8");
    expect(preview).toContain("{...CANVAS_PREVIEW_EDGE}");
    expect(CANVAS_PREVIEW_EDGE.stroke).toBe("var(--canvas-edge)");
  });
});

/** 共用那串里,某个选择器下的某个声明的值(没有就是 undefined)。 */
function declared(selector: string, property: string): string | undefined {
  for (const one of CANVAS_EDGE_CLASS.split(/\s+/)) {
    const prefix = selector ? `[${selector}]:` : "";
    if (!one.startsWith(`${prefix}[${property}:`)) continue;
    return one.slice(prefix.length + property.length + 2, -1);
  }
  return undefined;
}

describe("共用的连线外观", () => {
  it("任意值选择器里的下划线都转义了 —— 否则 Tailwind 把 `__` 换成空格,规则选不中任何东西", () => {
    const selectors = CANVAS_EDGE_CLASS.split(/\s+/).flatMap((one) => one.match(/^\[&[^\]]*\]/) ?? []);
    expect(selectors.length).toBeGreaterThan(10);
    for (const selector of selectors) expect(selector, selector).not.toMatch(/(?<!\\)__/);
  });

  it("每一项都是字面量 —— Tailwind 从源码文本里扫类名,插值出来的它看不见", () => {
    const source = readFileSync(join(SRC, HOME), "utf8");
    const body = source.slice(source.indexOf("export const CANVAS_EDGE_CLASS"), source.indexOf('].join(" ");'));
    expect(body).not.toContain("${");
  });

  it("平时的线色走令牌、跟着主题;选中是主色;点阵退成底纹", () => {
    expect(declared("", "--xy-edge-stroke")).toBe("var(--canvas-edge)");
    expect(declared("", "--xy-edge-stroke-selected")).toBe("var(--primary)");
    expect(declared("", "--xy-connectionline-stroke")).toBe("var(--primary)");
    expect(declared("", "--xy-background-pattern-color")).toBe("var(--canvas-dot)");
  });

  it("线宽三档和 CANVAS_EDGE_WIDTH 对得上:平时、悬停、选中,运行走过取选中那一档", () => {
    expect(declared("", "--xy-edge-stroke-width")).toBe(String(CANVAS_EDGE_WIDTH.rest));
    expect(declared("", "--xy-connectionline-stroke-width")).toBe(String(CANVAS_EDGE_WIDTH.rest));
    expect(declared(String.raw`&_.react-flow\_\_edge:hover`, "--xy-edge-stroke-width")).toBe(String(CANVAS_EDGE_WIDTH.hover));
    expect(declared(String.raw`&_.react-flow\_\_edge.selected`, "--xy-edge-stroke-width")).toBe(String(CANVAS_EDGE_WIDTH.selected));
    expect(declared(String.raw`&_.react-flow\_\_edges_.react-flow\_\_edge.canvas-edge-taken`, "--xy-edge-stroke-width")).toBe(
      String(CANVAS_EDGE_WIDTH.selected),
    );
    expect(CANVAS_EDGE_WIDTH.rest).toBeLessThan(CANVAS_EDGE_WIDTH.hover);
    expect(CANVAS_EDGE_WIDTH.hover).toBeLessThan(CANVAS_EDGE_WIDTH.selected);
  });

  it("每种颜色变体都落到一个语义令牌上,经 xyflow 的线色变量", () => {
    const expected: Record<Exclude<CanvasEdgeTone, "reference">, string> = {
      true: "var(--success)",
      false: "var(--destructive)",
      data: "var(--primary)",
      mismatch: "var(--warning)",
      taken: "var(--success)",
      pending: "var(--primary)",
    };
    for (const [tone, token] of Object.entries(expected)) {
      const className = canvasEdgeClass(tone as CanvasEdgeTone)!;
      expect(declared(`&_.${className}`, "--xy-edge-stroke"), tone).toBe(token);
    }
  });

  it("只有悬停直接写 stroke,而且选中的线不吃它 —— 选中态读的是 --xy-edge-stroke-selected", () => {
    const strokes = CANVAS_EDGE_CLASS.split(/\s+/).filter((one) => /:\[stroke:/.test(one));
    expect(strokes).toHaveLength(1);
    expect(strokes[0]).toContain(String.raw`.react-flow\_\_edge:not(.selected):hover`);
    //: 往前景色混,混的是**这根线自己的**颜色 —— 真绿悬停还是绿的。
    expect(strokes[0]).toContain("var(--xy-edge-stroke)");
    expect(strokes[0]).toContain("var(--foreground)");
  });

  it("流动虚线、待定虚线、拖线途中那根各有图案;线帽是圆的", () => {
    expect(declared(String.raw`&_.canvas-edge-flow_.react-flow\_\_edge-path`, "stroke-dasharray")).toBeDefined();
    expect(CANVAS_EDGE_CLASS).toContain(String.raw`[&_.canvas-edge-flow_.react-flow\_\_edge-path]:motion-safe:animate-edge-flow`);
    const pending = declared(String.raw`&_.canvas-edge-pending_.react-flow\_\_edge-path`, "stroke-dasharray");
    expect(pending).toBeDefined();
    //: 拖线途中和松手后待定的是**同一个样子**,线只在连上那一刻换一次(虚 → 实)。
    expect(declared(String.raw`&_.react-flow\_\_connection-path`, "stroke-dasharray")).toBe(pending);
    expect(declared(String.raw`&_.react-flow\_\_edge-path`, "stroke-linecap")).toBe("round");
    expect(declared(String.raw`&_.react-flow\_\_edge-path`, "stroke-linejoin")).toBe("round");
  });

  it("canvasEdgeClass:引用那种不挂类;颜色和流动虚线分开给", () => {
    expect(canvasEdgeClass("reference")).toBeUndefined();
    expect(canvasEdgeClass("true")).toBe("canvas-edge-true");
    expect(canvasEdgeClass("data", { flow: true })).toBe("canvas-edge-data canvas-edge-flow");
    expect(canvasEdgeClass("taken", { flow: true })).toBe("canvas-edge-taken canvas-edge-flow");
  });

  it("箭头:闭合三角,按画布坐标定大小(不随线宽胀缩),颜色取线自己的", () => {
    expect(CANVAS_EDGE_MARKER.type).toBe(MarkerType.ArrowClosed);
    expect(CANVAS_EDGE_MARKER.markerUnits).toBe("userSpaceOnUse");
    expect(CANVAS_EDGE_MARKER.color).toBe("context-stroke");
    //: xyflow 的箭头画在 20 格的 viewBox 里,三角占 5×8 格(再加 1 格描边)。换算成 px 之后,
    //: 箭头的长要是线宽的 3 倍以上、宽不超过 8 倍 —— 此前 4.5×7px 的那一粒就是太小。
    const scale = CANVAS_EDGE_MARKER.width / 20;
    expect(6 * scale).toBeGreaterThanOrEqual(3 * CANVAS_EDGE_WIDTH.rest);
    expect(9 * scale).toBeLessThanOrEqual(8 * CANVAS_EDGE_WIDTH.rest);
    expect(CANVAS_EDGE_MARKER.height).toBe(CANVAS_EDGE_MARKER.width);
  });

  it("每条边带的选项:共用的箭头,够宽的命中带", () => {
    expect(CANVAS_EDGE_OPTIONS.markerEnd).toBe(CANVAS_EDGE_MARKER);
    expect(CANVAS_EDGE_OPTIONS.interactionWidth).toBeGreaterThanOrEqual(20);
  });
});
