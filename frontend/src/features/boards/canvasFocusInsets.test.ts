import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 画布上的「跳过去看」不能照整块画布居中。
 *
 * 右栏的智能体、执行历史是**盖在画布上**的,不占版面 —— React Flow 量到的永远是整块画布。
 * 照它居中,目标就正好落在面板底下:用户点了讨论侧栏里的「在画布中查看」,画布动了,
 * 评论却在智能体那一栏后面,看着像"点了没反应"。
 *
 * 违反了不会报错,只会跳到看不见的地方,所以钉在这里。判据是**用没用那条算过遮挡的路**:
 *   · `centerCanvasViewport` / `fitCanvasViewport` —— 照没被盖住的那块算
 *   · `instance.setCenter` —— 照整块画布算,跳转类的动作不许再用
 */
const read = (path: string) => readFileSync(join(import.meta.dirname, "..", "..", path), "utf8");
/** 去掉注释 —— 免得棘轮被"注释里提到 setCenter"喂饱。 */
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/^\s*\*.*$/gm, "");

describe("跳转要避开右栏面板", () => {
  it("画板画布不再自己 setCenter —— 那条路不认识遮挡", () => {
    expect(strip(read("features/boards/BoardCanvas.tsx"))).not.toMatch(/\.setCenter\(/);
  });

  it("画板画布向页面要「哪块看得见」,而不是自己猜", () => {
    // 谁盖住了画布由页面知道,画布多大由画布知道 —— 两边各说各的那一半。
    const canvas = read("features/boards/BoardCanvas.tsx");
    expect(canvas).toMatch(/getInsets\?: \(surface: HTMLElement\) => CanvasViewportInsets/);
    expect(read("features/boards/BoardsView.tsx")).toContain("getInsets={getCanvasInsets}");
  });

  it("两张画布都把讨论跳转交给算过遮挡的那条路", () => {
    for (const [path, call] of [
      ["features/boards/BoardCanvas.tsx", "centerOn({ x, y })"],
      ["features/workflows/WorkflowsView.tsx", "getCanvasInsets()"],
    ] as const) {
      const source = read(path);
      // 取**最后**一次:第一次是接口里的类型声明,拿它切等于什么也没断言。
      const at = source.lastIndexOf(path.includes("workflows") ? "onJumpToComment" : "focusComment:");
      expect(at, `${path} 缺少讨论跳转`).toBeGreaterThan(0);
      expect(source.slice(at, at + 900), `${path} 的讨论跳转没算遮挡`).toContain(call);
    }
  });
});
