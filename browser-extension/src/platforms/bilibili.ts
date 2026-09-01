import type { TranscriptCue } from "../shared/types";

type BilibiliCue = { from?: unknown; to?: unknown; content?: unknown };


/** Convert Bilibili's subtitle body into the extension's platform-neutral cue model. */
export function normalizeBilibiliTranscript(payload: unknown): TranscriptCue[] {
  if (!payload || typeof payload !== "object") return [];
  const body = (payload as { body?: unknown }).body;
  if (!Array.isArray(body)) return [];

  const cues: TranscriptCue[] = [];
  for (const raw of body as BilibiliCue[]) {
    const start = Number(raw.from);
    const end = Number(raw.to);
    const text = typeof raw.content === "string" ? raw.content.replace(/\s+/g, " ").trim() : "";
    if (!Number.isFinite(start) || !Number.isFinite(end) || !text) continue;
    cues.push({ start: Math.max(0, start), end: Math.max(start, end), text });
  }
  return cues;
}
