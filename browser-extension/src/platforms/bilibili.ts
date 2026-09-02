import type { Transcript, TranscriptCue, TranscriptTrack } from "../shared/types";

type BilibiliCue = { from?: unknown; to?: unknown; content?: unknown };
type LooseRecord = Record<string, any>;

export type BilibiliTranscriptTrack = TranscriptTrack & { url: string };

type ReadBilibiliTranscriptOptions = {
  bvid: string;
  cid: string;
  trackId?: string;
  fetchText: (url: string) => Promise<string>;
};

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

function parseJson(body: string, message: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(message);
  }
}

/** Always refresh Bilibili's listing: subtitle URLs are signed and page globals survive some revisits. */
export async function readBilibiliTranscript({
  bvid,
  cid,
  trackId,
  fetchText,
}: ReadBilibiliTranscriptOptions): Promise<Transcript> {
  const listingUrl = `https://api.bilibili.com/x/player/v2?bvid=${encodeURIComponent(bvid)}&cid=${encodeURIComponent(cid)}`;
  const listing = parseJson(await fetchText(listingUrl), "B 站返回了无法识别的字幕清单");
  const tracks = (listing as LooseRecord)?.data?.subtitle?.subtitles;
  const candidates = listBilibiliTranscriptTracks(tracks);
  if (candidates.length === 0) throw new Error("当前视频没有可用字幕");
  const track = candidates.find((item) => item.id === trackId) || candidates[0];
  const subtitleUrl = track.url.startsWith("//") ? `https:${track.url}` : track.url;
  const payload = parseJson(await fetchText(subtitleUrl), "B 站返回了无法识别的字幕内容");
  const cues = normalizeBilibiliTranscript(payload);
  if (cues.length === 0) throw new Error("字幕内容为空");
  return {
    trackId: track.id,
    language: track.language,
    languageLabel: track.languageLabel,
    cues,
    tracks: candidates.map(({ url: _url, ...candidate }) => candidate),
  };
}
