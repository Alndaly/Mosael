/**
 * 坐标换算只此一份(P5/P6)。
 *
 * 这四套坐标系之间曾经各乘各的,踩过三次:点击全偏到左上角(物理像素当 CSS)、面板里可信点击脱靶
 * (没乘面板缩放)、顶栏压住网页(CSS 当 DIP)。所以把它们收在一个文件里,并用测试钉住取整方向。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: accountViews / pageDriver 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { captureToCss, cssToDip, dipToCss, pageToDip, pageToView, safeZoom } = require("./coords.cjs") as {
  captureToCss: (captured: { width: number; height: number }, cssSize: [number, number]) => { width: number; height: number } | null;
  cssToDip: (rect: { x: number; y: number; width: number; height: number }, zoom: number) => { x: number; y: number; width: number; height: number };
  dipToCss: (rect: { x: number; y: number; width: number; height: number }, zoom: number) => { x: number; y: number; width: number; height: number };
  pageToDip: (value: number, options?: { pageZoom?: number; hostZoom?: number }) => number;
  pageToView: (value: number, pageZoom: number) => number;
  safeZoom: (value: unknown) => number;
};

describe("坐标换算", () => {
  it("缩放 1 时两边相等(最常见的路径不该被取整弄偏)", () => {
    const rect = { x: 56, y: 56, width: 1200, height: 800 };
    expect(cssToDip(rect, 1)).toEqual(rect);
  });

  it("放大 125%:左上向上取、右下向下取 —— 宁可窄半像素也不压住外壳", () => {
    expect(cssToDip({ x: 56, y: 56, width: 100, height: 100 }, 1.25)).toEqual({
      x: 70,
      y: 70,
      width: 125,
      height: 125,
    });
    // 0.3 那种非整数比例:同样只往内收。
    const dip = cssToDip({ x: 10, y: 10, width: 100, height: 50 }, 1.1);
    expect(dip.width).toBeLessThanOrEqual(110);
    expect(dip.height).toBeLessThanOrEqual(55);
    expect(dipToCss(dip, 1.1).width).toBeCloseTo(dip.width / 1.1, 5);
  });

  it("页面 CSS → 视图 CSS:面板缩到 0.3 时点击坐标要跟着缩", () => {
    expect(pageToView(1000, 0.3)).toBeCloseTo(300, 5);
    expect(pageToDip(1000, { pageZoom: 0.3, hostZoom: 1.25 })).toBeCloseTo(375, 5);
  });

  it("缩放值坏了按 1 算(除零比脱靶更难查)", () => {
    for (const value of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, undefined, "x"]) {
      expect(safeZoom(value)).toBe(1);
    }
  });

  it("Retina 截图要缩回窗口 CSS 尺寸;本来就一致就不动它", () => {
    expect(captureToCss({ width: 1600, height: 1136 }, [800, 568])).toEqual({ width: 800, height: 568 });
    expect(captureToCss({ width: 800, height: 568 }, [800, 568])).toBeNull();
    expect(captureToCss({ width: 0, height: 0 }, [800, 568])).toBeNull();
  });
});
