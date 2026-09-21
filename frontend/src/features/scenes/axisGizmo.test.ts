/**
 * 视口角上那个坐标轴控件的几何。
 *
 * 这部分**看不出对错** —— 轴画反了、前后压错了,画面上仍然是六个小球,只有当你点「+X」却转到
 * 了背面才发现。所以拿数钉住:哪个轴落在屏幕的哪一侧、谁在前谁在后、排序是不是从后往前。
 *
 * 轴的约定跟场景数据走:**Y 朝上**。相机默认看向 -Z。
 */

import { describe, expect, it } from "vitest";

import { axisLabel, axisVector, gizmoHandles, type Orientation } from "./axisGizmo";

/** 没转过的相机:看向 -Z,+X 在右,+Y 在上。 */
const IDENTITY: Orientation = [0, 0, 0, 1];
/** 绕 Y 转 +90°:相机改看向 -X,于是世界的 +X 跑到了它背后。 */
const TURNED: Orientation = [0, Math.SQRT1_2, 0, Math.SQRT1_2];

function byId(orientation: Orientation) {
  return Object.fromEntries(gizmoHandles(orientation).map((one) => [one.id, one]));
}

describe("坐标轴控件", () => {
  it("六个轴柄,正负各一,id 不重复", () => {
    const handles = gizmoHandles(IDENTITY);
    expect(handles).toHaveLength(6);
    expect(new Set(handles.map((one) => one.id)).size).toBe(6);
    expect(handles.filter((one) => one.label).map((one) => one.label).sort()).toEqual(["X", "Y", "Z"]);
    // 负向不写字母 —— 写上就挤成一团(Blender 也是空心球)。
    expect(handles.filter((one) => one.sign < 0).every((one) => one.label === "")).toBe(true);
  });

  it("默认视角下:+X 在右、+Y 在上、+Z 朝着人", () => {
    const at = byId(IDENTITY);
    expect(at["x+"].x).toBeCloseTo(1, 6);
    expect(at["x+"].y).toBeCloseTo(0, 6);
    // 屏幕 y 向下,所以"在上"是负的 —— 这一条错了,整个控件会上下颠倒。
    expect(at["y+"].y).toBeCloseTo(-1, 6);
    expect(at["z+"].depth).toBeCloseTo(1, 6);
    expect(at["z-"].depth).toBeCloseTo(-1, 6);
  });

  it("相机转过去之后,被它背在身后的那个轴 depth 为正", () => {
    // 绕 Y 转 +90° 之后相机看向 -X,所以世界 +X 在它背后 = 朝着人。
    const at = byId(TURNED);
    expect(at["x+"].depth).toBeCloseTo(1, 6);
    expect(at["x-"].depth).toBeCloseTo(-1, 6);
    // 这时 +Z 落到屏幕**左边**:相机看向 -X,它的右手边是世界的 -Z。
    expect(at["z+"].x).toBeCloseTo(-1, 6);
    expect(at["z+"].depth).toBeCloseTo(0, 6);
  });

  it("从后往前排好 —— 前面的后画,才压得住背面的", () => {
    for (const orientation of [IDENTITY, TURNED, [0.2, 0.4, 0.1, 0.88] as Orientation]) {
      const depths = gizmoHandles(orientation).map((one) => one.depth);
      expect(depths).toEqual([...depths].sort((a, b) => a - b));
    }
  });

  it("轴柄永远落在单位圆上", () => {
    // 落点由朝向旋转而来,长度必须守恒;不守恒说明四元数那段写错了,而画面上只是"有点歪"。
    // 必须是**单位**四元数:长度守恒是旋转的性质,拿一个没归一化的数去要求它是在测自己写错的题。
    const raw = [0.3, -0.2, 0.55, 0.75];
    const norm = Math.hypot(...raw);
    const unit = raw.map((v) => v / norm) as unknown as Orientation;
    for (const one of gizmoHandles(unit)) {
      expect(Math.hypot(one.x, one.y, one.depth)).toBeCloseTo(1, 6);
    }
  });

  it("点哪个球就站到哪一侧", () => {
    expect(axisVector("y", 1)).toEqual([0, 1, 0]);
    expect(axisVector("y", -1)).toEqual([0, -1, 0]);
    expect(axisVector("z", -1)).toEqual([0, 0, -1]);
  });

  it("读屏软件听到的是「从上方看」,不是「y 加」", () => {
    expect(axisLabel("y", 1)).toBe("从上方看");
    expect(axisLabel("y", -1)).toBe("从下方看");
    expect(axisLabel("z", 1)).toBe("从正面看");
    expect(axisLabel("x", -1)).toBe("从左侧看");
  });
});
