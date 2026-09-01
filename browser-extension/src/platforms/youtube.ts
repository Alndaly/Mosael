import type { TranscriptCue, TranscriptTrack } from "../shared/types";

type YouTubeSegment = { utf8?: unknown };
type YouTubeEvent = { tStartMs?: unknown; dDurationMs?: unknown; segs?: unknown };
type LooseRecord = Record<string, any>;

export type YouTubeTranscriptTrack = TranscriptTrack & { url: string };

function label(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const record = value as LooseRecord;
  if (typeof record.simpleText === "string") return record.simpleText;
  if (Array.isArray(record.runs)) return record.runs.map((item: LooseRecord) => item?.text || "").join("");
  return "";
}

/** Enumerate native and YouTube-translated tracks, keeping a human source first when available. */
export function listYouTubeTranscriptTracks(player: unknown): YouTubeTranscriptTrack[] {
  const renderer = (player as LooseRecord)?.captions?.playerCaptionsTracklistRenderer;
  const rawTracks = renderer?.captionTracks;
  if (!Array.isArray(rawTracks) || rawTracks.length === 0) return [];
  const preferred = rawTracks.find((item: LooseRecord) => item?.kind !== "asr") || rawTracks[0];
  const ordered = [preferred, ...rawTracks.filter((item: LooseRecord) => item !== preferred)];
  const tracks: YouTubeTranscriptTrack[] = ordered.flatMap((track: LooseRecord, index: number) => {
    const url = String(track.baseUrl || "");
    if (!url) return [];
    return [{
      id: `youtube:source:${String(track.vssId || track.languageCode || index)}`,
      language: String(track.languageCode || ""),
      languageLabel: label(track.name) || String(track.languageCode || "字幕"),
      kind: "source" as const,
      url,
    }];
  });
  const translations = Array.isArray(renderer?.translationLanguages) ? renderer.translationLanguages : [];
  const translationBaseUrl = tracks[0]?.url;
  if (!translationBaseUrl) return tracks;
  for (const language of translations as LooseRecord[]) {
    const code = String(language?.languageCode || "");
    if (!code || tracks.some((track) => track.language === code)) continue;
    const endpoint = new URL(translationBaseUrl);
    endpoint.searchParams.set("tlang", code);
    tracks.push({
      id: `youtube:translated:${code}`,
      language: code,
      languageLabel: label(language?.languageName) || code,
      kind: "translated",
      url: endpoint.toString(),
    });
  }
  return tracks;
}


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
  return cues.map((cue, index) => {
    if (cue.end > cue.start) return cue;
    const nextStart = cues[index + 1]?.start;
    return { ...cue, end: typeof nextStart === "number" && nextStart > cue.start ? nextStart : cue.start + 2 };
  });
}

/** Parse json3 without exposing Chrome's low-level JSON error for an empty timed-text response. */
export function parseYouTubeTranscriptBody(body: string): TranscriptCue[] {
  if (!body.trim()) throw new Error("YouTube 没有返回字幕内容，请确认该视频已开启字幕后重试");
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    throw new Error("YouTube 返回了无法识别的字幕格式，请刷新视频页面后重试");
  }
  const cues = normalizeYouTubeTranscript(payload);
  if (cues.length === 0) throw new Error("YouTube 字幕内容为空");
  return cues;
}
