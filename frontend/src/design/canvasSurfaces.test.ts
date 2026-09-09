import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  CANVAS_GLASS_SURFACE_CLASS,
  CANVAS_WINDOW_SURFACE_CLASS,
} from "@/components/app/canvasPanelLayout";

/**
 * 画布上的浮层是**一种材质、两种高度**。
 *
 * 收成一处之前,同一张画布上并存着三套表面:生成合成器用模态表面、便签/音频/裁剪合成器和
 * 评论卡用实色的 popover、面板用画布浮层 —— 三种背景、三种影子,挨在一起一眼看得出不是一套。
 * 而且它们**看起来是不透明的**:窗口本身有 alpha,里面那个 `--field: #ffffff` 的输入框却是实色,
 * 于是浮窗最大的一块是白的,alpha 等于白给。
 *
 * 这条盯的是那两件事:透得出来、影子看得见,以及两种高度用的是同一种材质。
 */
const css = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8");

/** 取某个选择器块里的一条自定义属性(最后一次声明为准,和层叠一致)。 */
function token(selector: string, name: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const block = css.match(new RegExp(`${escaped} \\{([\\s\\S]*?)\\n\\}`));
  if (!block) throw new Error(`Missing ${selector} block`);
  const matches = [...block[1].matchAll(new RegExp(`--${name}:([^;]*);`, "g"))];
  if (!matches.length) throw new Error(`Missing --${name} in ${selector}`);
  return matches[matches.length - 1][1].trim();
}

/** 一条 box-shadow 里最深的那一层的 alpha。 */
function strongestAlpha(shadow: string): number {
  const alphas = [...shadow.matchAll(/\/\s*([0-9.]+)\s*\)/g)].map((one) => Number(one[1]));
  if (!alphas.length) throw new Error(`No alpha in ${shadow}`);
  return Math.max(...alphas);
}

describe("画布浮层", () => {
  for (const theme of [":root", ".dark"] as const) {
    it(`${theme}:浮窗的底色不是实色 —— 它盖住的每一块都是用户还想看见的画布`, () => {
      const tint = token(theme, "canvas-window-tint");
      const alpha = /\/\s*([0-9.]+)\s*\)/.exec(tint);
      expect(alpha, `--canvas-window-tint 需要带 alpha,收到 ${tint}`).not.toBeNull();
      expect(Number(alpha![1])).toBeLessThan(0.85);
    });

    it(`${theme}:浮窗的影子要比工具条胶囊明显 —— 它们会互相叠放,没有影子就分不出谁在上面`, () => {
      const windowShadow = token(theme, "shadow-canvas-window");
      expect(strongestAlpha(windowShadow)).toBeGreaterThan(
        strongestAlpha(token(theme, "shadow-panel")),
      );
      // 单层做不到"既有接触感又有远处的软影";三层是这条影子的形状本身。
      expect(windowShadow.split("),").length).toBeGreaterThanOrEqual(3);
    });
  }

  it("透明是**可以退掉的**:不支持背景模糊、或用户要求减少透明时,回到实色", () => {
    // 半透明的表面一旦没有背后的模糊,压在照片或 3D 视口上就是一块读不出字的脏玻璃。
    // 这两条退路少哪一条,都会有一批人拿到那块脏玻璃。
    expect(css).toMatch(/@supports[^{]*backdrop-filter[\s\S]*?--canvas-window: var\(--canvas-window-tint\)/);
    expect(css).toMatch(
      /@media \(prefers-reduced-transparency: reduce\)[\s\S]*?--canvas-window: var\(--canvas-window-solid\)/,
    );
  });

  it("浮窗里的输入框跟着一起透 —— 否则窗口最大的一块是实色,alpha 等于白给", () => {
    const surface = css.match(/\.canvas-overlay-surface \{([\s\S]*?)\n {2}\}/);
    expect(surface, "缺少 .canvas-overlay-surface").not.toBeNull();
    for (const name of ["field", "control", "field-border"]) {
      expect(surface![1]).toContain(`--${name}: var(--modal-`);
    }
  });

  it("工具条和浮窗是同一种材质,只差一层影子", () => {
    const material = (value: string) =>
      value.split(" ").filter((one) => !one.startsWith("shadow-") && !one.startsWith("rounded-"));
    expect(material(CANVAS_WINDOW_SURFACE_CLASS)).toEqual(material(CANVAS_GLASS_SURFACE_CLASS));
    expect(CANVAS_WINDOW_SURFACE_CLASS).toContain("shadow-[var(--shadow-canvas-window)]");
    expect(CANVAS_GLASS_SURFACE_CLASS).toContain("shadow-[var(--shadow-panel)]");
  });
});
