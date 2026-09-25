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

/**
 * 管理控制台那一页读写的东西。**入口只对部署管理员显示,但权限在后端** —— 每条路由各自
 * `ensure_deployment_admin`,这里只是给它们起名字。
 */
export type AdminUser = components["schemas"]["AdminUserOut"];
export type AdminOverview = components["schemas"]["AdminOverviewOut"];
/** 注册邀请码。后端回的是裸 dict(没有 response_model),形状照 routes/auth.list_registration_invites 写。 */
export type RegistrationInvite = { code: string; note: string; used: boolean; expires_at: string };

/** `days`:两张图(任务活动、按人花费)的窗口;账户、工作区、素材是当前总数,不受它影响。 */
export function adminOverview(days: number): Promise<AdminOverview> {
  return api<AdminOverview>(`/api/admin/overview?days=${days}`);
}

export function adminUsers(): Promise<AdminUser[]> {
  return api<AdminUser[]>("/api/admin/users");
}

/** 删掉一个账号,以及只属于他的东西(范围与边界在后端 domain/members.delete_account)。 */
export function deleteAccount(userId: string): Promise<void> {
  return api<void>(`/api/admin/users/${userId}`, { method: "DELETE" });
}

export function setDeploymentAdmin(userId: string, granted: boolean): Promise<unknown> {
  return api(`/api/auth/users/${userId}/deployment-admin`, { method: "POST", body: JSON.stringify({ granted }) });
}

/** 登录页开屏问的那两件事;管理页只用其中的「收不收自助注册」。不需要登录就能读。 */
export function authBootstrap(): Promise<components["schemas"]["BootstrapOut"]> {
  return api<components["schemas"]["BootstrapOut"]>("/api/auth/bootstrap");
}

export function setOpenRegistration(open: boolean): Promise<{ open: boolean }> {
  return api<{ open: boolean }>("/api/admin/registration", { method: "PUT", body: JSON.stringify({ open }) });
}

export function registrationInvites(): Promise<RegistrationInvite[]> {
  return api<RegistrationInvite[]>("/api/auth/invites");
}

export function createRegistrationInvite(note: string): Promise<RegistrationInvite> {
  return api<RegistrationInvite>("/api/auth/invites", { method: "POST", body: JSON.stringify({ note }) });
}

export function oauthPending(
  pendingId: string,
): Promise<{ status: string; token?: string; user?: User; error?: string }> {
  return api(`/api/auth/oauth/pending/${pendingId}`);
}
