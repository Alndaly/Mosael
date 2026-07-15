import type { components } from "@/api/generated/schema";

export const API_BASE = "http://127.0.0.1:8800";

const TOKEN_KEY = "mibu.auth.token";
let authToken: string | null = typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (typeof window !== "undefined") {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export type User = components["schemas"]["UserOut"];
export type AuthOut = components["schemas"]["AuthOut"];

export type Workspace = components["schemas"]["WorkspaceOut"];
export type Project = components["schemas"]["ProjectOut"];
export type Asset = components["schemas"]["AssetOut"];
export type Sequence = components["schemas"]["SequenceOut"];
export type Track = components["schemas"]["TrackOut"];
export type Clip = components["schemas"]["ClipOut"];
export type Job = components["schemas"]["JobOut"];
export type GenerationModel = components["schemas"]["GenerationModelOut"];
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];
export type ScheduledTask = components["schemas"]["ScheduledTaskOut"];
export type RunScheduledTaskResponse = components["schemas"]["RunScheduledTaskResponse"];
export type Plugin = components["schemas"]["PluginOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const auth: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};
  const headers =
    init?.body instanceof FormData
      ? { ...auth, ...(init?.headers as Record<string, string> | undefined) }
      : { "Content-Type": "application/json", ...auth, ...(init?.headers as Record<string, string> | undefined) };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function assetFileUrl(assetId: string): string {
  // Media elements cannot send headers, so these URLs carry the token.
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/assets/${assetId}/file${suffix}`;
}

export function assetThumbnailUrl(assetId: string): string {
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/assets/${assetId}/thumbnail${suffix}`;
}

export interface WaveformData {
  version: number;
  duration: number;
  peaks: number[];
}

export function fetchWaveform(assetId: string): Promise<WaveformData> {
  return api<WaveformData>(`/api/assets/${assetId}/waveform`);
}

export function insertClip(
  sequenceId: string,
  body: { track_id: string; asset_id: string; timeline_start: number; src_in: number; src_out: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips`, { method: "POST", body: JSON.stringify(body) });
}

export function moveClip(
  sequenceId: string,
  clipId: string,
  body: { timeline_start: number; track_id?: string | null },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/move`, {
    method: "PATCH",
    body: JSON.stringify(body),
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

export function addTrack(sequenceId: string, kind: "video" | "audio"): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks`, { method: "POST", body: JSON.stringify({ kind }) });
}

export function removeTrack(sequenceId: string, trackId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}`, { method: "DELETE" });
}

export function setClipEffects(sequenceId: string, clipId: string, effects: Record<string, unknown>): Promise<Sequence> {
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

export function renameProject(projectId: string, name: string): Promise<Project> {
  return api<Project>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteProject(projectId: string): Promise<unknown> {
  return api(`/api/projects/${projectId}`, { method: "DELETE" });
}

export function renameAsset(assetId: string, name: string): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteAsset(assetId: string): Promise<unknown> {
  return api(`/api/assets/${assetId}`, { method: "DELETE" });
}

export function exportSequence(sequenceId: string): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/export`, { method: "POST" });
}

export async function importAsset(params: {
  workspaceId: string;
  projectId: string;
  file: File;
  name?: string;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  form.set("project_id", params.projectId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  return api<Asset>("/api/assets/import", { method: "POST", body: form });
}
