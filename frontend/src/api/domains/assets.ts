import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type Asset = components["schemas"]["AssetOut"];

export interface RemoteEntry {
  id: string;
  url: string;
  title: string;
  duration: number | null;
  uploader: string;
  thumbnail: string;
  /** Actual available height choices, highest first. Empty means the shallow probe did not know. */
  heights?: number[];
}

export interface UrlProbe {
  title: string;
  is_playlist: boolean;
  entries: RemoteEntry[];
  truncated: boolean;
  /** One-based offset of this page. */
  start?: number;
}

export interface WaveformData {
  version: number;
  duration: number;
  peaks: number[];
}

function assetUrl(assetId: string, representation: "file" | "preview" | "thumbnail" | "filmstrip" | "proxy") {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/${representation}${suffix}`;
}

/** Probe metadata without downloading the media stream. */
export function probeUrl(
  workspaceId: string,
  url: string,
  profileId?: string | null,
  start = 1,
): Promise<UrlProbe> {
  return api<UrlProbe>("/api/assets/probe-url", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, url, profile_id: profileId || null, start }),
  });
}

/** Download selected remote entries into the asset library as one background job. */
export function importFromUrl(body: {
  workspace_id: string;
  project_id?: string | null;
  items: { url: string; title: string }[];
  kind: "video" | "audio";
  max_height?: number;
  profile_id?: string | null;
}): Promise<Job> {
  return api<Job>("/api/assets/import-url", { method: "POST", body: JSON.stringify(body) });
}

/** Import a path visible to the bundled desktop backend. */
export function importLocalAsset(workspaceId: string, path: string, projectId?: string): Promise<Asset> {
  return api<Asset>("/api/assets/import-local", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, path, project_id: projectId ?? null }),
  });
}

/** Original asset bytes. Media elements carry auth in the query because they cannot add headers. */
export function assetFileUrl(assetId: string): string {
  return assetUrl(assetId, "file");
}

/** Browser-compatible full-size preview; HEIC originals are derived to JPEG on demand. */
export function assetPreviewUrl(assetId: string): string {
  return assetUrl(assetId, "preview");
}

export function assetThumbnailUrl(assetId: string): string {
  return assetUrl(assetId, "thumbnail");
}

/** Uniformly sampled frames used by the editor filmstrip. */
export function assetFilmstripUrl(assetId: string): string {
  return assetUrl(assetId, "filmstrip");
}

/** The 720p preview proxy decoded by the WebCodecs compositor. */
export function assetProxyUrl(assetId: string): string {
  return assetUrl(assetId, "proxy");
}

/** Save one video frame as a new asset without mutating the source. */
export function grabAssetFrame(assetId: string, at: number, projectId?: string | null): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}/frame`, {
    method: "POST",
    body: JSON.stringify({ at, project_id: projectId ?? null }),
  });
}

/** Render the sequence playhead, including DOM overlays, into a new asset. */
export function grabSequenceFrame(sequenceId: string, at: number): Promise<Asset> {
  return api<Asset>(`/api/sequences/${sequenceId}/frame`, { method: "POST", body: JSON.stringify({ at }) });
}

export function fetchWaveform(assetId: string): Promise<WaveformData> {
  return api<WaveformData>(`/api/assets/${assetId}/waveform`);
}

export function listAssets(workspaceId: string, projectId?: string): Promise<Asset[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (projectId) params.set("project_id", projectId);
  return api<Asset[]>(`/api/assets?${params.toString()}`);
}

export function renameAsset(assetId: string, name: string): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function setAssetTags(assetId: string, tags: string[]): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ tags }) });
}

export function deleteAsset(assetId: string): Promise<unknown> {
  return api(`/api/assets/${assetId}`, { method: "DELETE" });
}

/** Empty language lets the engine detect it; empty engine follows the saved ASR preference. */
export function transcribeAsset(assetId: string, language = "", engine = ""): Promise<Job> {
  const params = new URLSearchParams();
  if (language) params.set("language", language);
  if (engine) params.set("engine", engine);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return api<Job>(`/api/assets/${assetId}/transcribe${query}`, { method: "POST" });
}

/** Create a new GIF asset without mutating the source video. */
export function convertVideoToGif(
  assetId: string,
  options: { fps?: number; width?: number; start?: number; duration?: number | null } = {},
): Promise<Job> {
  return api<Job>(`/api/assets/${assetId}/convert-gif`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}

export async function importAsset(params: {
  workspaceId: string;
  /** Omit projectId for a workspace-level asset; editor imports attach to a project. */
  projectId?: string;
  file: File;
  name?: string;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.projectId) form.set("project_id", params.projectId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  return api<Asset>("/api/assets/import", { method: "POST", body: form });
}
