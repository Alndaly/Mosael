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
  it("interpolates linearly between control points", () => {
    const c: [number, number][] = [[0, 0], [0.5, 0.8], [1, 1]];
    expect(evalCurve(c, 0.25)).toBeCloseTo(0.4); // halfway to (0.5,0.8)
    expect(evalCurve(c, 0.75)).toBeCloseTo(0.9); // halfway from 0.8 to 1
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
    // luma doubles-then-clamps via [[0,0],[0.5,1]]; r is identity.
    // For x=0.25: channel(r)=0.25 → master(0.25)=0.5. Table has 33 samples (N=32),
    // index 8 = x=0.25.
    const c: ColorCurves = {
      ...IDENTITY_CURVES,
      luma: [[0, 0], [0.5, 1], [1, 1]],
    };
    const tables = colorCurvesTables(c);
    expect(tables).not.toBeNull();
    const r = tables!.r.split(" ").map(Number);
    expect(r.length).toBe(33);
    expect(r[8]).toBeCloseTo(0.5, 2); // master(0.25) with the doubling luma
    expect(r[16]).toBeCloseTo(1, 2); // master(0.5)=1
  });
});
