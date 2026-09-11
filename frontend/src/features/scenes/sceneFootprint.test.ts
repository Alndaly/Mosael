import { describe, expect, it } from "vitest";

import { bounds, cameraPaths, footprints, type ScenePreviewData } from "./sceneFootprint";

describe("场景缩略图的俯视占地", () => {
  it("方体按 width×depth 摊开,圆体按直径见方 —— 一屋子柱子不该全画成箱子", () => {
    const data: ScenePreviewData = {
      objects: [
        { kind: "box", position: [1, 0, 2], parameters: { width: 4, depth: 6 } },
        { kind: "cylinder", position: [0, 0, 0], parameters: { radius: 1.5, width: 99, depth: 99 } },
      ],
    };
    const [box, cylinder] = footprints(data);
    expect([box.x, box.z, box.w, box.d]).toEqual([1, 2, 4, 6]);
    // 圆体不看 width/depth —— 它们对圆柱没有意义,拿来用就画错了。
    expect([cylinder.w, cylinder.d]).toEqual([3, 3]);
  });

  it("占地要乘 scale 的 x/z,而不是 y", () => {
    const [mark] = footprints({
      objects: [{ kind: "box", parameters: { width: 2, depth: 2 }, scale: [3, 10, 0.5] }],
    });
    expect([mark.w, mark.d]).toEqual([6, 1]);
  });

  it("相机和灯是位置标记,不按它们的 parameters 占地", () => {
    const marks = footprints({
      objects: [
        { kind: "camera", position: [5, 2, 5], parameters: { width: 50, depth: 50 } },
        { kind: "light", position: [0, 4, 0] },
      ],
    });
    expect(marks.every((mark) => mark.w < 1 && mark.d < 1)).toBe(true);
    expect([marks[0].x, marks[0].z]).toEqual([5, 5]);
  });

  it("只有走过两个以上位置的相机才算一条运镜路线", () => {
    const paths = cameraPaths({
      objects: [
        { kind: "camera", path: [[0, 1, 0], [3, 1, 4]] },
        { kind: "camera", path: [[9, 1, 9]] },
        { kind: "box" },
      ],
    });
    // 取的是地面坐标 (x, z),中间那个 y 不参与。
    expect(paths).toEqual([[[0, 0], [3, 4]]]);
  });

  it("画框要把旋转过的物体整个框住,不裁掉一角", () => {
    // 一块 10×1 的板子转 45°,对角线伸到约 ±5 —— 按未旋转的半宽 0.5 去框就会切掉两头。
    const view = bounds(footprints({
      objects: [{ kind: "box", position: [0, 0, 0], rotation: [0, 45, 0], parameters: { width: 10, depth: 1 } }],
    }), []);
    expect(view.x).toBeLessThanOrEqual(-5);
    expect(view.x + view.w).toBeGreaterThanOrEqual(5);
  });

  it("空场景给一块默认地,而不是一个零尺寸的 viewBox", () => {
    const view = bounds([], []);
    expect(view.w).toBeGreaterThan(0);
    expect(view.d).toBeGreaterThan(0);
  });

  it("缺字段、非数字都不该把整张图算崩", () => {
    const marks = footprints({
      objects: [
        { kind: "box" },
        { kind: "box", position: [Number.NaN, 0, 1] as unknown as [number, number, number] },
      ],
    });
    expect(marks).toHaveLength(2);
    expect(marks.every((mark) => Number.isFinite(mark.x) && mark.w > 0)).toBe(true);
  });
});
