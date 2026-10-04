import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type BrowserProfile = components["schemas"]["BrowserProfileOut"];
export type BrowserSession = components["schemas"]["BrowserSessionOut"];

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

/** 人在应用里手动打开了这个档案:记下网址(下次直接接着开)和「最近使用」。 */
export function recordBrowserProfileOpened(profileId: string, url: string): Promise<BrowserProfile> {
  return api<BrowserProfile>(`/api/browser/profiles/${profileId}/opened`, { method: "POST", body: JSON.stringify({ url }) });
}

export function deleteBrowserProfile(profileId: string): Promise<unknown> {
  return api(`/api/browser/profiles/${profileId}`, { method: "DELETE" });
}

/** 一个浏览器自动化会话是谁开的(悬浮卡片的标题)。不是会话的 id(发布账号的卡片)回 404。 */
export function getBrowserSession(sessionId: string): Promise<BrowserSession> {
  return api<BrowserSession>(`/api/browser/sessions/${encodeURIComponent(sessionId)}`);
}
