import type { components } from "@/api/generated/schema";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type User = components["schemas"]["UserOut"] & {
  display_name: string;
  signature: string;
};
export type AuthOut = Omit<components["schemas"]["AuthOut"], "user"> & { user: User };

export function uploadAvatar(file: File): Promise<User> {
  const form = new FormData();
  form.set("file", file);
  return api<User>("/api/auth/me/avatar", { method: "POST", body: form });
}

/** Avatar URLs carry the token because an `<img>` cannot add authorization headers. */
export function userAvatarUrl(userId: string, avatarKey: string | null | undefined): string {
  if (!avatarKey) return "";
  const token = getAuthToken();
  const suffix = token ? `&token=${token}` : "";
  return `${API_BASE}/api/auth/users/${userId}/avatar?v=${encodeURIComponent(avatarKey)}${suffix}`;
}

export function updateMe(body: { username: string; display_name: string; signature: string }): Promise<User> {
  return api<User>("/api/auth/me", { method: "PATCH", body: JSON.stringify(body) });
}

export function updatePassword(body: { current_password: string; new_password: string }): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>("/api/auth/me/password", { method: "POST", body: JSON.stringify(body) });
}

/** Start OAuth in the system browser, then poll the pending exchange for an application token. */
export function oauthProviders(): Promise<{ providers: string[] }> {
  return api<{ providers: string[] }>("/api/auth/oauth/providers");
}

export function oauthStart(provider: string): Promise<{ pending_id: string; url: string }> {
  return api<{ pending_id: string; url: string }>(`/api/auth/oauth/${provider}/start`, { method: "POST" });
}

/** 管理员共享给成员的本机文件夹(见后端 domain/host_files)。登录就能读,改它要部署管理员。 */
export type SharedHostFolders = components["schemas"]["SharedHostFolders"];

export function getSharedHostFolders(): Promise<SharedHostFolders> {
  return api<SharedHostFolders>("/api/admin/shared-host-folders");
}

export function setSharedHostFolders(folders: string[]): Promise<SharedHostFolders> {
  return api<SharedHostFolders>("/api/admin/shared-host-folders", { method: "PUT", body: JSON.stringify({ folders }) });
}

export function oauthPending(
  pendingId: string,
): Promise<{ status: string; token?: string; user?: User; error?: string }> {
  return api(`/api/auth/oauth/pending/${pendingId}`);
}
