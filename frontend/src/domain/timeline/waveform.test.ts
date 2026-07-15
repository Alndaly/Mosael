import { describe, expect, it } from "vitest";

import { downsamplePeaks, slicePeaks, waveformPolygonPoints } from "./waveform";

describe("slicePeaks", () => {
  const peaks = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]; // 10s asset

  it("slices proportionally to the src range", () => {
    expect(slicePeaks(peaks, 10, 2, 5)).toEqual([0.3, 0.4, 0.5]);
  });

  it("returns the full range for a full clip", () => {
    expect(slicePeaks(peaks, 10, 0, 10)).toEqual(peaks);
  });

  it("guards degenerate inputs", () => {
    expect(slicePeaks([], 10, 0, 5)).toEqual([]);
    expect(slicePeaks(peaks, 0, 0, 5)).toEqual([]);
    expect(slicePeaks(peaks, 10, 5, 5)).toEqual([]);
  });

  it("always yields at least one peak inside bounds", () => {
    expect(slicePeaks(peaks, 10, 0.01, 0.02).length).toBeGreaterThan(0);
  });
});

describe("downsamplePeaks", () => {
  it("preserves the maximum within each window", () => {
    const result = downsamplePeaks([0, 0.9, 0.1, 0.2, 0.8, 0], 3);
    expect(result).toEqual([0.9, 0.2, 0.8]);
  });

  it("passes through when already small enough", () => {
    expect(downsamplePeaks([0.1, 0.2], 10)).toEqual([0.1, 0.2]);
  });
});

describe("waveformPolygonPoints", () => {
  it("mirrors peaks around the midline", () => {
    const points = waveformPolygonPoints([1]);
    expect(points).toContain("0.000");
    expect(points).toContain("1.000");
  });

  it("returns empty for no peaks", () => {
    expect(waveformPolygonPoints([])).toBe("");
  });
});
