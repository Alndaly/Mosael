import { describe, expect, it } from "vitest";

import {
  clipDuration,
  clipEnd,
  formatFrameTimecode,
  formatRulerLabel,
  frameAt,
  overlapsAny,
  pxToTime,
  resolveMove,
  resolveTrim,
  rulerStep,
  rulerTicks,
  sequenceDuration,
  snapCandidates,
  snapTime,
  snapTimeTiered,
  snapToFrame,
  srcToTimeline,
  timelineToSrc,
  timeToPx,
  trackEdgeTimes,
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
    expect(resolveMove(moving, 3.05, [3], [], 40)).toBe(3);
  });

  it("snaps the trailing edge when it is the closer match", () => {
    // end lands near 6 → start becomes 4
    expect(resolveMove(moving, 3.9, [6], [], 40)).toBe(4);
  });

  it("clamps to zero", () => {
    expect(resolveMove(moving, -0.5, [], [], 40)).toBe(0);
  });

  it("same-track edge beats a nearer secondary candidate (the hijack bug)", () => {
    // 复现:头边缘离同轨邻居 0.13s(阈值内),尾边缘离一个次级候选(播放头/
    // 跨轨边缘)只有 0.025s。单池实现会让更近的次级候选赢 → 落点被劫持;
    // 两级实现必须吸到同轨的 5.806。
    const cam = clip("m", 0, 0, 5);
    expect(resolveMove(cam, 5.937, [5.806], [10.912], 40)).toBe(5.806);
  });

  it("falls back to secondary candidates when no primary is in range", () => {
    // 本轨无命中 → 播放头(次级)仍可吸附:end 5.95+2 → 8 附近无,start 5.95 → 6。
    expect(resolveMove(moving, 5.95, [], [6], 40)).toBe(6);
  });
});

describe("snapTimeTiered", () => {
  it("primary hit wins even when secondary is nearer", () => {
    expect(snapTimeTiered(5.1, [5], [5.08], 40)).toEqual({ time: 5, snapped: true });
  });

  it("uses secondary only when primary misses", () => {
    expect(snapTimeTiered(5.1, [9], [5.05], 40)).toEqual({ time: 5.05, snapped: true });
  });
});

describe("trackEdgeTimes", () => {
  it("collects only clip edges (no zero/playhead anchors)", () => {
    expect(trackEdgeTimes([clip("a", 2, 0, 3)], null)).toEqual([2, 5]);
    expect(trackEdgeTimes([clip("a", 2, 0, 3)], "a")).toEqual([]);
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

  it("end-trim is unbounded when assetDuration is null (images have no fixed length)", () => {
    // A still image can be stretched to any length — no source-duration ceiling.
    expect(resolveTrim(base, "end", 20, null)).toEqual({ timeline_start: 4, src_in: 1, src_out: 17 });
  });
});

describe("时间线 ↔ 源时间按速度换算", () => {
  // 2 倍速:时间线上 10s 长,源里 20s。
  const fast = { id: "f", timeline_start: 10, src_in: 4, src_out: 24, speed: 2 };

  it("时间线上走 1 秒,源里走 speed 秒", () => {
    expect(timelineToSrc(fast, 12)).toBe(8);
    expect(srcToTimeline(fast, 8)).toBe(12);
    expect(srcToTimeline(fast, timelineToSrc(fast, 17.5))).toBeCloseTo(17.5);
  });

  it("尾边拖到哪,片段就结束在哪(2 倍速不再缩一半)", () => {
    const result = resolveTrim(fast, "end", 15);
    expect(result.timeline_start + clipDuration({ ...fast, ...result })).toBeCloseTo(15);
    expect(result.src_out).toBeCloseTo(14);
  });

  it("头边拖动时尾部不动", () => {
    const result = resolveTrim(fast, "start", 12);
    expect(result.timeline_start).toBe(12);
    expect(result.src_in).toBeCloseTo(8);
    expect(result.timeline_start + clipDuration({ ...fast, ...result })).toBeCloseTo(clipEnd(fast));
  });

  it("头边最多退到源 0 点:2 倍速下源前面的 4 秒只占时间线 2 秒", () => {
    expect(resolveTrim(fast, "start", 0)).toEqual({ timeline_start: 8, src_in: 0, src_out: 24 });
  });

  it("尾边的素材上限按速度折算到时间线", () => {
    // 素材 30s:源里还剩 6s,时间线上只能再长 3s。
    const result = resolveTrim(fast, "end", 100, 30);
    expect(result.src_out).toBe(30);
    expect(result.timeline_start + clipDuration({ ...fast, ...result })).toBeCloseTo(23);
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

describe("帧对齐", () => {
  it("时间落到最近的帧上(按序列帧率)", () => {
    expect(frameAt(1.025, 30)).toBe(31);
    expect(snapToFrame(1.025, 30)).toBe(31 / 30);
    expect(snapToFrame(0.51, 25)).toBe(13 / 25);
    // 浮点累加的毛刺(0.1 * 30 = 3.0000000000000004)不该把帧号推到下一帧。
    expect(frameAt(0.1, 30)).toBe(3);
  });

  it("帧率缺失或非法时按 30fps,不产出 NaN", () => {
    expect(snapToFrame(1.025, 0)).toBe(31 / 30);
    expect(Number.isFinite(snapToFrame(2, Number.NaN))).toBe(true);
  });

  it("时间码精确到帧:HH:MM:SS:FF", () => {
    expect(formatFrameTimecode(0, 30)).toBe("00:00:00:00");
    expect(formatFrameTimecode(15 + 12 / 30, 30)).toBe("00:00:15:12");
    expect(formatFrameTimecode(3725 + 12 / 25, 25)).toBe("01:02:05:12");
    // 29.97 按 30 帧一秒计(非丢帧):帧号不会出现 30。
    expect(formatFrameTimecode(10, 29.97)).toBe("00:00:10:00");
    expect(formatFrameTimecode(-1, 30)).toBe("00:00:00:00");
  });
});

describe("timecode", () => {
  it("formats ruler labels", () => {
    expect(formatRulerLabel(0)).toBe("0:00");
    expect(formatRulerLabel(65)).toBe("1:05");
    expect(formatRulerLabel(3661)).toBe("1:01:01");
  });

  it("步长不到 1 秒时带小数,放大到最大也不出现重复的标签", () => {
    for (const pxPerSecond of [200, 240]) {
      const step = rulerStep(pxPerSecond);
      expect(step).toBeLessThan(1);
      const labels = rulerTicks(0, 3, pxPerSecond)
        .filter((tick) => tick.major)
        .map((tick) => formatRulerLabel(tick.time, step));
      expect(new Set(labels).size).toBe(labels.length);
    }
    expect(formatRulerLabel(0.5, 0.5)).toBe("0:00.5");
    expect(formatRulerLabel(61.2, 0.2)).toBe("1:01.2");
    // 整秒的刻度不带小数,和缩小时的标签一个样子。
    expect(formatRulerLabel(2, 0.5)).toBe("0:02");
  });
});
