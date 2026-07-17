import { describe, expect, it } from "vitest";

import {
  colorCurvesTables,
  curvesAreIdentity,
  evalCurve,
  IDENTITY_CURVES,
  type ColorCurves,
} from "@/features/editor/colorCurves";

describe("evalCurve", () => {
  it("is the identity line by default", () => {
    expect(evalCurve([[0, 0], [1, 1]], 0.4)).toBeCloseTo(0.4);
  });
  it("interpolates with monotone cubic Hermite (Fritsch–Carlson)", () => {
    const c: [number, number][] = [[0, 0], [0.5, 0.8], [1, 1]];
    // 切线:m0=1.6(端点=割线)、m1=调和加权 0.64、m2=0.4。手算的段内 Hermite 值:
    expect(evalCurve(c, 0.25)).toBeCloseTo(0.46, 5);
    expect(evalCurve(c, 0.75)).toBeCloseTo(0.915, 5);
    expect(evalCurve(c, 0.125)).toBeCloseTo(0.2225, 5);
    // 控制点本身精确命中。
    expect(evalCurve(c, 0.5)).toBeCloseTo(0.8);
  });
  it("keeps collinear points exactly linear (identity stays identity)", () => {
    const straight: [number, number][] = [[0, 0], [0.5, 0.5], [1, 1]];
    for (const x of [0.1, 0.3, 0.4, 0.7, 0.9]) expect(evalCurve(straight, x)).toBeCloseTo(x, 6);
  });
  it("clamps outside the point range", () => {
    const c: [number, number][] = [[0.2, 0.1], [0.8, 0.9]];
    expect(evalCurve(c, 0)).toBeCloseTo(0.1);
    expect(evalCurve(c, 1)).toBeCloseTo(0.9);
  });
  it("sorts unsorted control points", () => {
    expect(evalCurve([[1, 1], [0, 0], [0.5, 0.2]], 0.5)).toBeCloseTo(0.2);
  });
});

describe("curvesAreIdentity", () => {
  it("true for undefined and the identity set", () => {
    expect(curvesAreIdentity(undefined)).toBe(true);
    expect(curvesAreIdentity(IDENTITY_CURVES)).toBe(true);
  });
  it("false when any channel bends", () => {
    const c: ColorCurves = { ...IDENTITY_CURVES, r: [[0, 0.1], [1, 1]] };
    expect(curvesAreIdentity(c)).toBe(false);
  });
});

describe("colorCurvesTables (master∘channel order)", () => {
  it("returns null when identity", () => {
    expect(colorCurvesTables(IDENTITY_CURVES)).toBeNull();
  });

  it("applies channel curve first, then master on the result", () => {
    // luma ramps to 1 by x=0.5 via [[0,0],[0.5,1],[1,1]]; r is identity.
    // For x=0.25: channel(r)=0.25 → master(0.25)。FC 切线 m=[2,0,0],段内
    // Hermite 值 = 0.625(而非线性的 0.5)。表有 33 个样本(N=32),索引 8 即 x=0.25。
    const c: ColorCurves = {
      ...IDENTITY_CURVES,
      luma: [[0, 0], [0.5, 1], [1, 1]],
    };
    const tables = colorCurvesTables(c);
    expect(tables).not.toBeNull();
    const r = tables!.r.split(" ").map(Number);
    expect(r.length).toBe(33);
    expect(r[8]).toBeCloseTo(0.625, 3); // master(0.25) with the fast-ramp luma
    expect(r[16]).toBeCloseTo(1, 2); // master(0.5)=1 (control point hit exactly)
  });
});
