import { describe, expect, it } from "vitest";

import {
  clipDuration,
  clipEnd,
  formatRulerLabel,
  formatTimecode,
  overlapsAny,
  pxToTime,
  resolveMove,
  resolveTrim,
  rulerStep,
  rulerTicks,
  sequenceDuration,
  snapCandidates,
  snapTime,
  timeToPx,
} from "./geometry";

const clip = (id: string, start: number, srcIn: number, srcOut: number) => ({
  id,
  timeline_start: start,
  src_in: srcIn,
  src_out: srcOut,
});

describe("scale conversion", () => {
  it("round-trips time and pixels", () => {
    expect(timeToPx(2.5, 40)).toBe(100);
    expect(pxToTime(100, 40)).toBe(2.5);
    expect(pxToTime(100, 0)).toBe(0);
  });
});

describe("clip math", () => {
  it("computes duration, end, and sequence duration", () => {
    const a = clip("a", 0, 1, 5);
    const b = clip("b", 10, 0, 2);
    expect(clipDuration(a)).toBe(4);
    expect(clipEnd(b)).toBe(12);
    expect(sequenceDuration([a, b])).toBe(12);
    expect(sequenceDuration([])).toBe(0);
  });
});

describe("ruler", () => {
  it("chooses coarser steps as zoom decreases", () => {
    expect(rulerStep(200)).toBe(0.5);
    expect(rulerStep(40)).toBe(2);
    expect(rulerStep(2)).toBe(60);
  });

  it("emits majors on step boundaries and minors between", () => {
    const ticks = rulerTicks(0, 4, 80); // step = 1s, minor = 0.25s
    const majors = ticks.filter((t) => t.major).map((t) => t.time);
    expect(majors).toEqual([0, 1, 2, 3, 4]);
    expect(ticks.some((t) => t.time === 0.25 && !t.major)).toBe(true);
  });

  it("never starts before zero", () => {
    const ticks = rulerTicks(-5, 2, 80);
    expect(ticks[0].time).toBe(0);
  });
});

describe("snapping", () => {
  it("collects clip edges, zero, and playhead once", () => {
    const candidates = snapCandidates([clip("a", 2, 0, 3)], null, 7);
    expect(candidates).toEqual([0, 2, 5, 7]);
  });

  it("excludes the dragged clip's own edges", () => {
    const candidates = snapCandidates([clip("a", 2, 0, 3)], "a", 0);
    expect(candidates).toEqual([0]);
  });

  it("snaps within threshold and not outside it", () => {
    // 8px at 40 px/s = 0.2s threshold
    expect(snapTime(5.1, [5], 40)).toEqual({ time: 5, snapped: true });
    expect(snapTime(5.3, [5], 40)).toEqual({ time: 5.3, snapped: false });
  });

  it("prefers the nearest candidate", () => {
    expect(snapTime(5.06, [5, 5.1], 40).time).toBe(5.1);
  });
});

describe("resolveMove", () => {
  const moving = clip("m", 0, 0, 2);

  it("snaps the leading edge to a neighbor's end", () => {
    expect(resolveMove(moving, 3.05, [3], 40)).toBe(3);
  });

  it("snaps the trailing edge when it is the closer match", () => {
    // end lands near 6 → start becomes 4
    expect(resolveMove(moving, 3.9, [6], 40)).toBe(4);
  });

  it("clamps to zero", () => {
    expect(resolveMove(moving, -0.5, [], 40)).toBe(0);
  });
});

describe("resolveTrim", () => {
  const base = clip("t", 4, 1, 5); // 4s long on timeline [4, 8), source [1, 5)

  it("start-trim shifts timeline_start and src_in together", () => {
    expect(resolveTrim(base, "start", 5)).toEqual({ timeline_start: 5, src_in: 2, src_out: 5 });
  });

  it("start-trim cannot reveal material before src 0", () => {
    // src_in is 1, so timeline_start can move at most 1s earlier
    expect(resolveTrim(base, "start", 2)).toEqual({ timeline_start: 3, src_in: 0, src_out: 5 });
  });

  it("start-trim keeps a minimum duration", () => {
    const result = resolveTrim(base, "start", 100);
    expect(result.src_out - result.src_in).toBeCloseTo(0.05);
  });

  it("end-trim adjusts src_out only", () => {
    expect(resolveTrim(base, "end", 6)).toEqual({ timeline_start: 4, src_in: 1, src_out: 3 });
  });

  it("end-trim clamps to asset duration", () => {
    expect(resolveTrim(base, "end", 20, 6)).toEqual({ timeline_start: 4, src_in: 1, src_out: 6 });
  });
});

describe("overlapsAny", () => {
  const clips = [clip("a", 0, 0, 4), clip("b", 10, 0, 2)];

  it("detects overlap and respects exclusion", () => {
    expect(overlapsAny(clips, { start: 3, end: 5 })).toBe(true);
    expect(overlapsAny(clips, { start: 3, end: 5 }, "a")).toBe(false);
  });

  it("treats touching edges as non-overlapping", () => {
    expect(overlapsAny(clips, { start: 4, end: 10 })).toBe(false);
  });
});

describe("timecode", () => {
  it("formats working timecode", () => {
    expect(formatTimecode(0)).toBe("00:00.0");
    expect(formatTimecode(75.26)).toBe("01:15.2");
    expect(formatTimecode(-1.5)).toBe("-00:01.5");
  });

  it("formats ruler labels", () => {
    expect(formatRulerLabel(0)).toBe("0:00");
    expect(formatRulerLabel(65)).toBe("1:05");
    expect(formatRulerLabel(3661)).toBe("1:01:01");
  });
});
