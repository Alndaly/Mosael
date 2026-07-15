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
}

export function timeToPx(time: number, pxPerSecond: number): number {
  return time * pxPerSecond;
}

export function pxToTime(px: number, pxPerSecond: number): number {
  return pxPerSecond > 0 ? px / pxPerSecond : 0;
}

export function clipDuration(clip: ClipLike): number {
  return clip.src_out - clip.src_in;
}

export function clipEnd(clip: ClipLike): number {
  return clip.timeline_start + clipDuration(clip);
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

/* ---------- Snapping ---------- */

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

/* ---------- Move ---------- */

export function resolveMove(
  clip: ClipLike,
  rawStart: number,
  candidates: number[],
  pxPerSecond: number,
  thresholdPx = 8,
): number {
  const duration = clipDuration(clip);
  const startSnap = snapTime(rawStart, candidates, pxPerSecond, thresholdPx);
  const endSnap = snapTime(rawStart + duration, candidates, pxPerSecond, thresholdPx);
  let start = rawStart;
  if (startSnap.snapped && endSnap.snapped) {
    // Prefer whichever edge is closer to its candidate.
    const startDistance = Math.abs(startSnap.time - rawStart);
    const endDistance = Math.abs(endSnap.time - (rawStart + duration));
    start = startDistance <= endDistance ? startSnap.time : endSnap.time - duration;
  } else if (startSnap.snapped) {
    start = startSnap.time;
  } else if (endSnap.snapped) {
    start = endSnap.time - duration;
  }
  return Math.max(0, start);
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
    const minStart = Math.max(0, clip.timeline_start - clip.src_in);
    const start = Math.min(Math.max(rawTime, minStart), maxStart);
    const delta = start - clip.timeline_start;
    return {
      timeline_start: start,
      src_in: clip.src_in + delta,
      src_out: clip.src_out,
    };
  }
  const minEnd = clip.timeline_start + minDuration;
  const maxEnd =
    assetDuration != null ? clip.timeline_start + (assetDuration - clip.src_in) : Number.POSITIVE_INFINITY;
  const end = Math.min(Math.max(rawTime, minEnd), maxEnd);
  return {
    timeline_start: clip.timeline_start,
    src_in: clip.src_in,
    src_out: clip.src_in + (end - clip.timeline_start),
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

/** MM:SS.d — the editor's working precision readout. */
export function formatTimecode(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  const minutes = Math.floor(abs / 60);
  const secs = Math.floor(abs % 60);
  const tenths = Math.floor((abs * 10) % 10);
  return `${sign}${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${tenths}`;
}

/** Compact ruler label: M:SS below an hour, H:MM:SS above. */
export function formatRulerLabel(seconds: number): string {
  const abs = Math.max(0, Math.round(seconds));
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const secs = abs % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}
