import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type BrowserProfile = components["schemas"]["BrowserProfileOut"];

export function listBrowserProfiles(workspaceId: string): Promise<BrowserProfile[]> {
  return api<BrowserProfile[]>(`/api/browser/profiles?workspace_id=${workspaceId}`);
}

export function createBrowserProfile(body: {
  workspace_id: string;
  name: string;
  proxy?: string | null;
}): Promise<BrowserProfile> {
  return api<BrowserProfile>("/api/browser/profiles", { method: "POST", body: JSON.stringify(body) });
}

export function updateBrowserProfile(
  profileId: string,
  body: { name?: string; proxy?: string | null; enabled?: boolean },
): Promise<BrowserProfile> {
  return api<BrowserProfile>(`/api/browser/profiles/${profileId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteBrowserProfile(profileId: string): Promise<unknown> {
  return api(`/api/browser/profiles/${profileId}`, { method: "DELETE" });
}
