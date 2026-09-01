import type { TranscriptCue } from "../shared/types";

type YouTubeSegment = { utf8?: unknown };
type YouTubeEvent = { tStartMs?: unknown; dDurationMs?: unknown; segs?: unknown };


/** Convert YouTube's json3 timed-text payload into the extension's platform-neutral cue model. */
export function normalizeYouTubeTranscript(payload: unknown): TranscriptCue[] {
  if (!payload || typeof payload !== "object") return [];
  const events = (payload as { events?: unknown }).events;
  if (!Array.isArray(events)) return [];

  const cues: TranscriptCue[] = [];
  for (const raw of events as YouTubeEvent[]) {
    const startMs = Number(raw.tStartMs);
    if (!Number.isFinite(startMs) || !Array.isArray(raw.segs)) continue;
    const text = (raw.segs as YouTubeSegment[])
      .map((segment) => (typeof segment?.utf8 === "string" ? segment.utf8 : ""))
      .join("")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) continue;
    const durationMs = Number(raw.dDurationMs);
    const start = Math.max(0, startMs / 1000);
    const end = Number.isFinite(durationMs) && durationMs > 0 ? start + durationMs / 1000 : start;
    cues.push({ start, end, text });
  }
  return cues;
}
