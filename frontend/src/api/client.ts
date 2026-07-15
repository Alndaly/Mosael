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

export function deleteClip(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}`, { method: "DELETE" });
}

export function undoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/undo`, { method: "POST" });
}

export function redoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/redo`, { method: "POST" });
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
