import { describe, expect, it } from "vitest";

import { restoreColor, serializeColor } from "@/features/editor/useColorHistory";

describe("serializeColor", () => {
  it("captures only color + filter, ignoring other effects", () => {
    const s = serializeColor({ color: { saturation: 0.5 }, filter: "bw", pip: { x: 0.1 } });
    expect(JSON.parse(s)).toEqual({ color: { saturation: 0.5 }, filter: "bw" });
  });
  it("null-fills missing fields", () => {
    expect(JSON.parse(serializeColor({}))).toEqual({ color: null, filter: null });
    expect(JSON.parse(serializeColor(undefined))).toEqual({ color: null, filter: null });
  });
});

describe("restoreColor", () => {
  it("restores color + filter while preserving unrelated effects", () => {
    const effects = { color: { saturation: 0.9 }, pip: { x: 0.2 } };
    const snap = serializeColor({ color: { contrast: 0.2 }, filter: "warm" });
    expect(restoreColor(effects, snap)).toEqual({ color: { contrast: 0.2 }, filter: "warm", pip: { x: 0.2 } });
  });
  it("deletes color/filter when the snapshot had none", () => {
    const effects = { color: { saturation: 0.9 }, filter: "bw", pip: { x: 0.2 } };
    const clean = serializeColor({});
    expect(restoreColor(effects, clean)).toEqual({ pip: { x: 0.2 } });
  });
  it("round-trips through serialize", () => {
    const original = { color: { hue: -0.3, curves: { luma: [[0, 0], [1, 1]] } }, filter: undefined, text: "hi" };
    const restored = restoreColor({ text: "hi" }, serializeColor(original));
    expect(restored.color).toEqual(original.color);
    expect(restored.filter).toBeUndefined();
    expect(restored.text).toBe("hi");
  });
});
