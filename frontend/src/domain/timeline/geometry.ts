/**
 * Pure timeline geometry. No React, no stores, no API types — everything the
 * timeline UI computes lives here so it can be unit-tested exactly.
 * All times are in seconds, all distances in CSS pixels.
 */

export interface ClipLike {
  id: string;
  timeline_start: number;
  src_in: number;
  src_out: number;
  speed?: number;
}

export function timeToPx(time: number, pxPerSecond: number): number {
  return time * pxPerSecond;
}

export function pxToTime(px: number, pxPerSecond: number): number {
  return pxPerSecond > 0 ? px / pxPerSecond : 0;
}

export function clipDuration(clip: ClipLike): number {
  return (clip.src_out - clip.src_in) / (clip.speed || 1);
}

export function clipEnd(clip: ClipLike): number {
  return clip.timeline_start + clipDuration(clip);
}

/* ---------- 时间线 ↔ 源 ----------
 *
 * 片段在时间线上走 1 秒,源里走 speed 秒。切分点、修剪后的 src_in/src_out、插入预览的切口、
 * 刀片落点……凡是"时间线上这一刻对应源里哪一刻"的问题都经这一对函数 —— 此前各处手写一遍,
 * 有的乘了 speed、有的没乘(S 键在 2 倍速片段上切错位置、修剪尾边拖到 15 实际停在 12.5),
 * 而它们看起来都"差不多对",只有变速片段会露馅。 */

/** 时间线时刻 → 这一刻播放的源时刻。 */
export function timelineToSrc(clip: ClipLike, time: number): number {
  return clip.src_in + (time - clip.timeline_start) * (clip.speed || 1);
}

/** 源时刻 → 它出现在时间线上的时刻。 */
export function srcToTimeline(clip: ClipLike, srcTime: number): number {
  return clip.timeline_start + (srcTime - clip.src_in) / (clip.speed || 1);
}

export function sequenceDuration(clips: ClipLike[]): number {
  return clips.reduce((end, clip) => Math.max(end, clipEnd(clip)), 0);
}

/* ---------- Ruler ---------- */

const RULER_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

/** Smallest step whose label spacing stays readable at this zoom. */
export function rulerStep(pxPerSecond: number, minLabelPx = 72): number {
  for (const step of RULER_STEPS) {
    if (step * pxPerSecond >= minLabelPx) return step;
  }
  return RULER_STEPS[RULER_STEPS.length - 1];
}

export interface RulerTick {
  time: number;
  major: boolean;
}

/** Ticks covering [start, end], majors every step, minors at step/4. */
export function rulerTicks(start: number, end: number, pxPerSecond: number, minLabelPx = 72): RulerTick[] {
  const step = rulerStep(pxPerSecond, minLabelPx);
  const minor = step / 4;
  const ticks: RulerTick[] = [];
  const first = Math.max(0, Math.floor(start / minor) * minor);
  const epsilon = minor / 1000;
  for (let t = first; t <= end + epsilon; t += minor) {
    const time = Number(t.toFixed(6));
    const major = Math.abs(time / step - Math.round(time / step)) < 1e-6;
    ticks.push({ time, major });
  }
  return ticks;
}

/* ---------- Snapping ----------
 *
 * 吸附分两级:目标轨自身的片段边缘是第一优先级(用户拖动时肉眼在对齐的就是
 * 它们),播放头/零点/其他轨道的边缘只在本轨无命中时才参与。单一候选池的老
 * 实现里,字幕轨密密麻麻的 cue 边界和看不见的播放头会以更近的距离"抢走"
 * 同轨对接 — 明明贴着邻居片段松手,落点却被劫持到别处("段落之间吸不上")。 */

/** Edge times worth snapping to: clip boundaries, playhead, and zero. */
export function snapCandidates(clips: ClipLike[], excludeClipId: string | null, playhead: number): number[] {
  const times = new Set<number>([0, playhead]);
  for (const clip of clips) {
    if (clip.id === excludeClipId) continue;
    times.add(clip.timeline_start);
    times.add(clipEnd(clip));
  }
  return [...times].sort((a, b) => a - b);
}

/** 单条轨道上的片段边缘(两级吸附的第一优先级)。 */
export function trackEdgeTimes(clips: ClipLike[], excludeClipId: string | null): number[] {
  const times = new Set<number>();
  for (const clip of clips) {
    if (clip.id === excludeClipId) continue;
    times.add(clip.timeline_start);
    times.add(clipEnd(clip));
  }
  return [...times].sort((a, b) => a - b);
}

/** Snap a time to the nearest candidate within thresholdPx at this zoom. */
export function snapTime(
  time: number,
  candidates: number[],
  pxPerSecond: number,
  thresholdPx = 8,
): { time: number; snapped: boolean } {
  const threshold = pxToTime(thresholdPx, pxPerSecond);
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const candidate of candidates) {
    const distance = Math.abs(candidate - time);
    if (distance <= threshold && distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
  }
  return best === null ? { time, snapped: false } : { time: best, snapped: true };
}

/** 两级吸附:primary(目标轨片段边缘)命中即定,否则再试 secondary。 */
export function snapTimeTiered(
  time: number,
  primary: number[],
  secondary: number[],
  pxPerSecond: number,
  thresholdPx = 8,
): { time: number; snapped: boolean } {
  const first = snapTime(time, primary, pxPerSecond, thresholdPx);
  if (first.snapped) return first;
  return snapTime(time, secondary, pxPerSecond, thresholdPx);
}

/* ---------- Move ---------- */

/** 对一组候选点做双边吸附:片段的头、尾各自找最近命中,双双命中时取更近的
 *  一边。整组都没命中返回 null(好让上层降级到次级候选)。 */
function resolveMoveAgainst(
  clip: ClipLike,
  rawStart: number,
  candidates: number[],
  pxPerSecond: number,
  thresholdPx: number,
): number | null {
  const duration = clipDuration(clip);
  const startSnap = snapTime(rawStart, candidates, pxPerSecond, thresholdPx);
  const endSnap = snapTime(rawStart + duration, candidates, pxPerSecond, thresholdPx);
  if (startSnap.snapped && endSnap.snapped) {
    // Prefer whichever edge is closer to its candidate.
    const startDistance = Math.abs(startSnap.time - rawStart);
    const endDistance = Math.abs(endSnap.time - (rawStart + duration));
    return startDistance <= endDistance ? startSnap.time : endSnap.time - duration;
  }
  if (startSnap.snapped) return startSnap.time;
  if (endSnap.snapped) return endSnap.time - duration;
  return null;
}

export function resolveMove(
  clip: ClipLike,
  rawStart: number,
  primary: number[],
  secondary: number[],
  pxPerSecond: number,
  thresholdPx = 8,
): number {
  const first = resolveMoveAgainst(clip, rawStart, primary, pxPerSecond, thresholdPx);
  if (first !== null) return Math.max(0, first);
  const second = resolveMoveAgainst(clip, rawStart, secondary, pxPerSecond, thresholdPx);
  return Math.max(0, second ?? rawStart);
}

/* ---------- Trim ---------- */

export interface TrimResult {
  timeline_start: number;
  src_in: number;
  src_out: number;
}

export const MIN_CLIP_DURATION = 0.05;

/**
 * Trim one edge of a clip to a new timeline time, keeping source material
 * anchored (start-trim shifts src_in with the clip; end-trim adjusts src_out).
 * assetDuration bounds src_out when known.
 *
 * 入参 rawTime 与 minDuration 都是**时间线**秒;换成源秒一律经 timelineToSrc,所以变速片段的
 * 边缘停在指针所在处,头边拖动时尾部纹丝不动。
 */
export function resolveTrim(
  clip: ClipLike,
  edge: "start" | "end",
  rawTime: number,
  assetDuration: number | null = null,
  minDuration: number = MIN_CLIP_DURATION,
): TrimResult {
  if (edge === "start") {
    const maxStart = clipEnd(clip) - minDuration;
    // 源 0 点在时间线上的位置:头边最多退到这里(也不能退到时间线 0 之前)。
    const minStart = Math.max(0, srcToTimeline(clip, 0));
    const start = Math.min(Math.max(rawTime, minStart), maxStart);
    return {
      timeline_start: start,
      src_in: Math.max(0, timelineToSrc(clip, start)),
      src_out: clip.src_out,
    };
  }
  const minEnd = clip.timeline_start + minDuration;
  const maxEnd = assetDuration != null ? srcToTimeline(clip, assetDuration) : Number.POSITIVE_INFINITY;
  const end = Math.min(Math.max(rawTime, minEnd), maxEnd);
  return {
    timeline_start: clip.timeline_start,
    src_in: clip.src_in,
    src_out: assetDuration != null ? Math.min(assetDuration, timelineToSrc(clip, end)) : timelineToSrc(clip, end),
  };
}

/* ---------- Overlap ---------- */

export function overlapsAny(
  clips: ClipLike[],
  candidate: { start: number; end: number },
  excludeClipId: string | null = null,
): boolean {
  return clips.some(
    (clip) =>
      clip.id !== excludeClipId && candidate.start < clipEnd(clip) - 1e-9 && candidate.end > clip.timeline_start + 1e-9,
  );
}

/* ---------- Timecode ---------- */

/** Compact ruler label: M:SS below an hour, H:MM:SS above. */
export function formatRulerLabel(seconds: number): string {
  const abs = Math.max(0, Math.round(seconds));
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const secs = abs % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}
