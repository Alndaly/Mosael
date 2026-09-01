import type { TranscriptCue, TranscriptTrack } from "../shared/types";

type BilibiliCue = { from?: unknown; to?: unknown; content?: unknown };
type LooseRecord = Record<string, any>;

export type BilibiliTranscriptTrack = TranscriptTrack & { url: string };

/** Keep Bilibili's human-authored tracks ahead of AI-generated alternatives. */
export function listBilibiliTranscriptTracks(rawTracks: unknown): BilibiliTranscriptTrack[] {
  if (!Array.isArray(rawTracks)) return [];
  return rawTracks
    .map((item: LooseRecord, index: number) => ({ item, index }))
    .sort((left, right) => Number(Boolean(left.item?.ai_type)) - Number(Boolean(right.item?.ai_type)))
    .flatMap(({ item, index }) => {
      const url = String(item.subtitle_url || item.subtitleUrl || "");
      if (!url) return [];
      return [{
        id: `bilibili:source:${String(item.id_str || item.id || item.lan || index)}`,
        language: String(item.lan || ""),
        languageLabel: String(item.lan_doc || item.lan || "字幕"),
        kind: "source" as const,
        url,
      }];
    });
}


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
