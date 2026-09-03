import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type Sequence = components["schemas"]["SequenceOut"];
export type Track = components["schemas"]["TrackOut"];
export type Clip = components["schemas"]["ClipOut"];

export function insertClip(
  sequenceId: string,
  body: {
    track_id: string;
    asset_id: string;
    timeline_start: number;
    src_in: number;
    src_out: number;
    ripple?: boolean;
  },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips`, { method: "POST", body: JSON.stringify(body) });
}

export function moveClip(
  sequenceId: string,
  clipId: string,
  body: { timeline_start: number; track_id?: string | null; ripple?: boolean },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/move`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** One batch is one operation and therefore one undo step. */
export function deleteClipsBatch(sequenceId: string, clipIds: string[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/delete-batch`, {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds }),
  });
}

export function rippleDeleteClipsBatch(sequenceId: string, clipIds: string[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/ripple-delete-batch`, {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds }),
  });
}

export function moveClipsBatch(
  sequenceId: string,
  moves: { clip_id: string; timeline_start: number; track_id?: string | null }[],
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/move-batch`, {
    method: "PATCH",
    body: JSON.stringify({ moves }),
  });
}

export function trimClip(
  sequenceId: string,
  clipId: string,
  body: { timeline_start: number; src_in: number; src_out: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/trim`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function cutClipRange(
  sequenceId: string,
  clipId: string,
  body: { src_start: number; src_end: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/cut-range`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteClip(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}`, { method: "DELETE" });
}

export function cutClipRanges(
  sequenceId: string,
  clipId: string,
  ranges: Array<{ src_start: number; src_end: number }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/cut-ranges`, {
    method: "POST",
    body: JSON.stringify({ ranges }),
  });
}

export function cutClipRangesBatch(
  sequenceId: string,
  cuts: Array<{ clip_id: string; ranges: Array<{ src_start: number; src_end: number }> }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/cut-ranges`, {
    method: "POST",
    body: JSON.stringify({ cuts }),
  });
}

export function setClipSpeed(sequenceId: string, clipId: string, speed: number): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/speed`, {
    method: "PATCH",
    body: JSON.stringify({ speed }),
  });
}

export function setClipGain(sequenceId: string, clipId: string, gain: number, muted: boolean): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/gain`, {
    method: "PATCH",
    body: JSON.stringify({ gain, muted }),
  });
}

export function detachClipAudio(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/detach-audio`, { method: "POST" });
}

export function setClipTransform(
  sequenceId: string,
  clipId: string,
  transform: Record<string, unknown>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/transform`, {
    method: "PATCH",
    body: JSON.stringify({ transform }),
  });
}

export function setSequenceReframe(
  sequenceId: string,
  reframe: { width: number; height: number; fill_mode: string },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/reframe`, {
    method: "PATCH",
    body: JSON.stringify(reframe),
  });
}

export function rippleDeleteClip(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/ripple`, { method: "DELETE" });
}

export function splitClip(sequenceId: string, clipId: string, srcTime: number): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/split`, {
    method: "POST",
    body: JSON.stringify({ src_time: srcTime }),
  });
}

export function splitClipAtPoints(sequenceId: string, clipId: string, srcTimes: number[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/split-points`, {
    method: "POST",
    body: JSON.stringify({ src_times: srcTimes }),
  });
}

export function splitClipAtPointsBatch(
  sequenceId: string,
  splits: Array<{ clip_id: string; src_times: number[] }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/split-points`, {
    method: "POST",
    body: JSON.stringify({ splits }),
  });
}

export function setTrackState(
  sequenceId: string,
  trackId: string,
  body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function addTrack(sequenceId: string, kind: "video" | "audio" | "subtitle"): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks`, {
    method: "POST",
    body: JSON.stringify({ kind }),
  });
}

export function moveTrack(sequenceId: string, trackId: string, direction: "up" | "down"): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}/move`, {
    method: "PATCH",
    body: JSON.stringify({ direction }),
  });
}

export function generateSubtitles(
  sequenceId: string,
  trackId: string,
  cues: Array<{ text: string; timeline_start: number; duration: number }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/subtitles/generate`, {
    method: "POST",
    body: JSON.stringify({ track_id: trackId, cues }),
  });
}

export function setSubtitleStyle(sequenceId: string, style: Record<string, unknown>): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/subtitle-style`, {
    method: "PUT",
    body: JSON.stringify({ style }),
  });
}

/** Backend safety limit for one translation request; the client exposes an unbounded operation. */
const TRANSLATE_BATCH = 400;

export async function translateTexts(
  workspaceId: string,
  texts: string[],
  targetLang: string,
  engine: "google" | "ai" = "google",
  /** Awaited after every batch so callers can persist incremental progress atomically. */
  onBatch?: (translations: string[], offset: number) => void | Promise<void>,
): Promise<{ translations: string[] }> {
  const translations: string[] = [];
  for (let start = 0; start < texts.length; start += TRANSLATE_BATCH) {
    const batch = texts.slice(start, start + TRANSLATE_BATCH);
    // Sequential batches avoid multiplying pressure on an upstream provider; the backend
    // already parallelizes work inside each batch.
    const result = await api<{ translations: string[] }>("/api/translate", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, texts: batch, target_lang: targetLang, engine }),
    });
    translations.push(...result.translations);
    await onBatch?.(result.translations, start);
  }
  return { translations };
}

export function insertTextClip(
  sequenceId: string,
  body: { track_id: string; text: string; timeline_start: number; duration: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/text-clips`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function setClipText(sequenceId: string, clipId: string, text: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/text`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });
}

/** Retext many clips in one revision and one undo step. */
export function setClipTexts(
  sequenceId: string,
  texts: { clip_id: string; text: string }[],
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/texts`, {
    method: "PATCH",
    body: JSON.stringify({ texts }),
  });
}

/** Removing a populated track is destructive and therefore requires an explicit flag. */
export function removeTrack(sequenceId: string, trackId: string, withClips = false): Promise<Sequence> {
  const suffix = withClips ? "?with_clips=true" : "";
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}${suffix}`, { method: "DELETE" });
}

export function setClipEffects(
  sequenceId: string,
  clipId: string,
  effects: Record<string, unknown>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/effects`, {
    method: "PATCH",
    body: JSON.stringify({ effects }),
  });
}

export function undoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/undo`, { method: "POST" });
}

export function redoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/redo`, { method: "POST" });
}

export interface ExportParams {
  resolution: "original" | "1080p" | "720p" | "480p";
  fps: number | null;
  quality: "high" | "standard" | "compact";
}

export function exportSequence(sequenceId: string, params?: ExportParams): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/export`, {
    method: "POST",
    ...(params ? { body: JSON.stringify(params) } : {}),
  });
}

export interface Lut {
  id: string;
  workspace_id: string;
  name: string;
  original_filename: string;
  size: number;
  created_at?: string | null;
}

export function listLuts(workspaceId: string): Promise<Lut[]> {
  return api<Lut[]>(`/api/luts?workspace_id=${workspaceId}`);
}

export async function uploadLut(params: { workspaceId: string; file: File; name?: string }): Promise<Lut> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  return api<Lut>("/api/luts", { method: "POST", body: form });
}

export function deleteLut(lutId: string): Promise<void> {
  return api<void>(`/api/luts/${lutId}`, { method: "DELETE" });
}

export interface Font {
  id: string;
  workspace_id: string;
  /** Family from the font name table, which is what libass matches during export. */
  family: string;
  original_filename: string;
  size: number;
  created_at?: string | null;
}

export function listFonts(workspaceId: string): Promise<Font[]> {
  return api<Font[]>(`/api/fonts?workspace_id=${workspaceId}`);
}

export async function uploadFont(params: { workspaceId: string; file: File }): Promise<Font> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  form.set("file", params.file);
  return api<Font>("/api/fonts", { method: "POST", body: form });
}

export function deleteFont(fontId: string): Promise<void> {
  return api<void>(`/api/fonts/${fontId}`, { method: "DELETE" });
}

export function fontFileUrl(fontId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/fonts/${fontId}/file${suffix}`;
}
