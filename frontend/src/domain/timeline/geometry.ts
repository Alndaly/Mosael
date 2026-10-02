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

/* ---------- 帧 ----------
 *
 * 成片是一帧一帧的:落在两帧之间的切点、修剪边缘、播放头,导出时都会被吞成某一帧,而预览里
 * 看到的是另一个位置。所以用户能放下的每一个时间点(播放头、标尺点击、拖动、修剪、切分)
 * 都先吸到序列帧率的帧上;逐帧移动按帧号加减,而不是把 1/fps 一次次浮点累加。 */

const FALLBACK_FPS = 30;

function usableFps(fps: number): number {
  return Number.isFinite(fps) && fps > 0 ? fps : FALLBACK_FPS;
}

/** 这个时刻落在第几帧(四舍五入到最近的帧)。 */
export function frameAt(time: number, fps: number): number {
  // 先截掉浮点毛刺再取整:0.1 * 30 是 3.0000000000000004,不该算成"3 帧多一点"。
  return Math.round(Number((time * usableFps(fps)).toFixed(6)));
}

/** 第 frame 帧的起点时刻。 */
export function frameTime(frame: number, fps: number): number {
  return frame / usableFps(fps);
}

/** 吸到最近的一帧上。 */
export function snapToFrame(time: number, fps: number): number {
  return frameTime(frameAt(time, fps), fps);
}

/** HH:MM:SS:FF —— 剪辑软件通用的帧级时间码(非丢帧:29.97 按 30 帧一秒计)。 */
export function formatFrameTimecode(seconds: number, fps: number): string {
  const base = Math.max(1, Math.round(usableFps(fps)));
  const total = Math.max(0, frameAt(seconds, fps));
  const frames = total % base;
  const wholeSeconds = Math.floor(total / base);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(Math.floor(wholeSeconds / 3600))}:${pad(Math.floor((wholeSeconds % 3600) / 60))}:${pad(wholeSeconds % 60)}:${pad(frames)}`;
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
/** 切开 / 挖掉之后剩下的一截短于这么多**源秒**就不留(和后端 _timeline.MIN_CUT_REMAINDER 同值)。 */
export const MIN_CUT_REMAINDER = 0.05;

/** 修剪能到的时间线范围:头边不越过左邻居的尾巴,尾边不越过右邻居的头(同轨不重叠,后端同样夹住)。 */
export interface TrimLimits {
  min: number;
  max: number;
}

export function trimLimits(trackClips: ClipLike[], clip: ClipLike): TrimLimits {
  let min = 0;
  let max = Number.POSITIVE_INFINITY;
  for (const other of trackClips) {
    if (other.id === clip.id) continue;
    if (clipEnd(other) <= clip.timeline_start + 1e-9) min = Math.max(min, clipEnd(other));
    else if (other.timeline_start >= clipEnd(clip) - 1e-9) max = Math.min(max, other.timeline_start);
  }
  return { min, max };
}

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
  limits: TrimLimits = { min: 0, max: Number.POSITIVE_INFINITY },
): TrimResult {
  if (edge === "start") {
    const maxStart = clipEnd(clip) - minDuration;
    // 源 0 点在时间线上的位置:头边最多退到这里(也不能退到时间线 0 之前、左邻居的尾巴之前)。
    const minStart = Math.max(0, limits.min, srcToTimeline(clip, 0));
    const start = Math.min(Math.max(rawTime, minStart), maxStart);
    return {
      timeline_start: start,
      src_in: Math.max(0, timelineToSrc(clip, start)),
      src_out: clip.src_out,
    };
  }
  const minEnd = clip.timeline_start + minDuration;
  const maxEnd = Math.min(limits.max, assetDuration != null ? srcToTimeline(clip, assetDuration) : Number.POSITIVE_INFINITY);
  const end = Math.min(Math.max(rawTime, minEnd), maxEnd);
  return {
    timeline_start: clip.timeline_start,
    src_in: clip.src_in,
    src_out: assetDuration != null ? Math.min(assetDuration, timelineToSrc(clip, end)) : timelineToSrc(clip, end),
  };
}

/* ---------- Overlap ---------- */

/**
 * 覆盖放下时,一段片段被 spans 盖住之后还露在外面的几截(时间线区间)。和后端 coverage.carve 同一口径:
 * 整段被盖住就没了;露出头 / 尾的各留一截;中间被盖住切成两截;剩下不到 MIN_CUT_REMAINDER 源秒的碎片不留。
 * 拖动预览靠它把「松手之后下层会被挖掉」提前画出来 —— 不然拖着看是叠在上面,松手才发现下面那段没了一块。
 */
export function uncoveredPieces(clip: ClipLike, spans: Array<{ start: number; end: number }>): Array<{ start: number; end: number }> {
  const speed = clip.speed || 1;
  const keeps = (from: number, to: number) => to - from > 1e-9 && (to - from) * speed > MIN_CUT_REMAINDER;
  let pieces = [{ start: clip.timeline_start, end: clipEnd(clip) }];
  for (const span of spans) {
    const next: Array<{ start: number; end: number }> = [];
    for (const piece of pieces) {
      if (span.end <= piece.start + 1e-9 || span.start >= piece.end - 1e-9) {
        next.push(piece);
        continue;
      }
      if (span.start > piece.start && keeps(piece.start, span.start)) next.push({ start: piece.start, end: span.start });
      if (span.end < piece.end && keeps(span.end, piece.end)) next.push({ start: span.end, end: piece.end });
    }
    pieces = next;
  }
  return pieces;
}

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

/**
 * Compact ruler label: M:SS below an hour, H:MM:SS above.
 *
 * 传了刻度步长且不到 1 秒时,不落在整秒上的刻度带一位小数(0:00.5)。此前一律取整秒:放大到
 * 半秒一格时 0.5 和 1 都写成 0:01,标尺上一排重复的标签,看不出哪格是哪格。
 */
export function formatRulerLabel(seconds: number, step = 1): string {
  const clamped = Math.max(0, seconds);
  const tenths = Math.round(clamped * 10) % 10;
  const fractional = step < 1 && tenths !== 0;
  const abs = fractional ? Math.floor(clamped) : Math.round(clamped);
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const secs = abs % 60;
  const tail = fractional ? `.${tenths}` : "";
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}${tail}`;
  return `${minutes}:${String(secs).padStart(2, "0")}${tail}`;
}
