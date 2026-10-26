import { describe, expect, it } from "vitest";

import { canvasBackingFor } from "./canvasSizing";

const sequence = { width: 1920, height: 1080 };

describe("canvasBackingFor", () => {
  it("按 CSS 尺寸乘 DPR 分配后备像素,而不是按序列分辨率", () => {
    expect(canvasBackingFor({ width: 960, height: 540 }, 2, sequence)).toEqual({
      width: 1920,
      height: 1080,
      scaleX: 1,
      scaleY: 1,
    });
  });

  it("监视器大于序列逻辑尺寸时仍按物理像素放大", () => {
    const backing = canvasBackingFor({ width: 1200, height: 675 }, 2, sequence);
    expect(backing).toMatchObject({ width: 2400, height: 1350 });
    expect(backing.scaleX).toBeCloseTo(1.25);
    expect(backing.scaleY).toBeCloseTo(1.25);
  });

  it("支持非整数缩放,并保证至少 1 像素", () => {
    expect(canvasBackingFor({ width: 800, height: 450 }, 1.5, sequence)).toMatchObject({
      width: 1200,
      height: 675,
    });
    expect(canvasBackingFor({ width: 0, height: 0 }, 2, sequence)).toMatchObject({
      width: 1,
      height: 1,
    });
  });

  it("宽高比有取整误差时分别映射,不把画面拉歪", () => {
    const backing = canvasBackingFor({ width: 1001, height: 563 }, 2, sequence);
    expect(backing.width).toBe(2002);
    expect(backing.height).toBe(1126);
    expect(backing.scaleX).not.toBe(backing.scaleY);
  });
});
