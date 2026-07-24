import { describe, expect, it } from "vitest";

import type { Transform } from "@/features/editor/TransformOverlay";
import { clipProgress, hasActiveKeyframes, removeKeyframe, sampleProp, sampleTransform, upsertKeyframe } from "@/features/editor/keyframes";

const base: Transform = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 };

describe("sampleProp", () => {
  it("holds the endpoint value outside the keyframe range", () => {
    const kfs = [{ t: 0.2, x: -1 }, { t: 0.8, x: 1 }];
    expect(sampleProp(kfs, "x", 0, 0)).toBe(-1); // before first → first
    expect(sampleProp(kfs, "x", 0, 1)).toBe(1); // after last → last
  });

  it("linearly interpolates between two keyframes", () => {
    const kfs = [{ t: 0, x: 0 }, { t: 1, x: 2 }];
    expect(sampleProp(kfs, "x", 0, 0.25)).toBeCloseTo(0.5);
    expect(sampleProp(kfs, "x", 0, 0.5)).toBeCloseTo(1);
  });

  it("falls back to the base value when the property has no keyframes", () => {
    const kfs = [{ t: 0, x: 1 }, { t: 1, x: 2 }]; // no scale points
    expect(sampleProp(kfs, "scale", 1.5, 0.5)).toBe(1.5);
  });

  it("ignores keyframes that don't carry the property (independent tracks)", () => {
    // opacity is keyed at t=0 and t=1; x only at t=0.5 → sampling x uses the single point
    const kfs = [{ t: 0, opacity: 0 }, { t: 0.5, x: 1 }, { t: 1, opacity: 1 }];
    expect(sampleProp(kfs, "opacity", 1, 0.5)).toBeCloseTo(0.5);
    expect(sampleProp(kfs, "x", 0, 0.9)).toBe(1); // only one x point → constant
  });
});

describe("hasActiveKeyframes", () => {
  it("is false with fewer than two points", () => {
    expect(hasActiveKeyframes({ ...base, keyframes: [{ t: 0, x: 1 }] })).toBe(false);
    expect(hasActiveKeyframes(base)).toBe(false);
  });
  it("is false when two points hold the same value (no motion)", () => {
    expect(hasActiveKeyframes({ ...base, keyframes: [{ t: 0, x: 1 }, { t: 1, x: 1 }] })).toBe(false);
  });
  it("is true when some property actually changes", () => {
    expect(hasActiveKeyframes({ ...base, keyframes: [{ t: 0, scale: 1 }, { t: 1, scale: 1.4 }] })).toBe(true);
  });
});

describe("sampleTransform", () => {
  it("returns the static transform untouched when no active keyframes", () => {
    const tf = { ...base, x: 0.5 };
    expect(sampleTransform(tf, 0.7)).toBe(tf);
  });
  it("drives a Ken-Burns zoom (scale 1 → 1.3) across the clip", () => {
    const tf: Transform = { ...base, keyframes: [{ t: 0, scale: 1 }, { t: 1, scale: 1.3 }] };
    expect(sampleTransform(tf, 0).scale).toBeCloseTo(1);
    expect(sampleTransform(tf, 0.5).scale).toBeCloseTo(1.15);
    expect(sampleTransform(tf, 1).scale).toBeCloseTo(1.3);
  });
  it("keeps rotation static (not keyframed)", () => {
    const tf: Transform = { ...base, rotation: 30, keyframes: [{ t: 0, opacity: 0 }, { t: 1, opacity: 1 }] };
    expect(sampleTransform(tf, 0.5).rotation).toBe(30);
  });
});

describe("clipProgress", () => {
  it("maps playhead to 0..1 within the clip, honoring speed", () => {
    const clip = { timeline_start: 10, src_in: 0, src_out: 4, speed: 1 }; // duration 4s
    expect(clipProgress(clip, 10)).toBeCloseTo(0);
    expect(clipProgress(clip, 12)).toBeCloseTo(0.5);
    expect(clipProgress(clip, 14)).toBeCloseTo(1);
    expect(clipProgress(clip, 20)).toBeCloseTo(1); // clamped
  });
  it("shortens output duration under 2x speed", () => {
    const clip = { timeline_start: 0, src_in: 0, src_out: 4, speed: 2 }; // output duration 2s
    expect(clipProgress(clip, 1)).toBeCloseTo(0.5);
  });
});

describe("upsert / remove", () => {
  it("adds a keyframe and keeps the track sorted by t", () => {
    const kfs = upsertKeyframe([{ t: 0.8, x: 1 }], 0.2, { x: -1 });
    expect(kfs.map((k) => k.t)).toEqual([0.2, 0.8]);
  });
  it("merges into an existing keyframe at the same t rather than duplicating", () => {
    const kfs = upsertKeyframe([{ t: 0.5, x: 1 }], 0.5, { opacity: 0.3 });
    expect(kfs).toHaveLength(1);
    expect(kfs[0]).toEqual({ t: 0.5, x: 1, opacity: 0.3 });
  });
  it("removes the nearest keyframe", () => {
    const kfs = removeKeyframe([{ t: 0.1, x: 0 }, { t: 0.6, x: 1 }], 0.55);
    expect(kfs.map((k) => k.t)).toEqual([0.1]);
  });
});
