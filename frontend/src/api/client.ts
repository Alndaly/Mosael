import type { components } from "@/api/generated/schema";

export const API_BASE = "http://127.0.0.1:8800";

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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
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
