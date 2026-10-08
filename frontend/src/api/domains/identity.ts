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

export function updatePassword(body: { current_password: string; new_password: string }): Promise<{ ok: boolean; signed_out: number }> {
  return api<{ ok: boolean; signed_out: number }>("/api/auth/me/password", { method: "POST", body: JSON.stringify(body) });
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

/** 内网访问的允许名单(见后端 core/outbound_guard):用户给的地址可以去的内网地址。只有部署管理员能看能改。 */
export type OutboundAllowlist = components["schemas"]["OutboundAllowlist"];

export function getOutboundAllowlist(): Promise<OutboundAllowlist> {
  return api<OutboundAllowlist>("/api/admin/outbound-allowlist");
}

export function setOutboundAllowlist(entries: string[]): Promise<OutboundAllowlist> {
  return api<OutboundAllowlist>("/api/admin/outbound-allowlist", { method: "PUT", body: JSON.stringify({ entries }) });
}

/**
 * 管理控制台那一页读写的东西。**入口只对部署管理员显示,但权限在后端** —— 每条路由各自
 * `ensure_deployment_admin`,这里只是给它们起名字。
 */
export type AdminUser = components["schemas"]["AdminUserOut"];
export type AdminOverview = components["schemas"]["AdminOverviewOut"];
/** 一张邀请链接(ADR 0054):进工作区的,或者不带工作区、只进这台部署的(此前的注册邀请码)。原文不在这里。 */
export type InviteLink = components["schemas"]["InviteLinkOut"];
/** 刚发出去的那一张:`code` 原文只在这一次;`web_url` 是部署配的网页地址(空 = 只有深链)。 */
export type IssuedInviteLink = components["schemas"]["IssuedInviteLinkOut"];
export type InviteLinkPreview = components["schemas"]["InviteLinkPreviewOut"];
export type InviteLinkJoined = components["schemas"]["InviteLinkJoinedOut"];

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

/** 部署管理员替成员重置密码:返回的临时密码只这一次给出(库里存哈希),他已登录的会话全部作废。 */
export function resetUserPassword(userId: string): Promise<components["schemas"]["AdminPasswordResetOut"]> {
  return api<components["schemas"]["AdminPasswordResetOut"]>(`/api/admin/users/${userId}/password`, { method: "POST" });
}

export type StorageOrphan = components["schemas"]["StorageOrphanOut"];
export type StorageOrphans = components["schemas"]["StorageOrphansOut"];

/** 数据目录里没人认领的文件(部署管理员看)。只列,不删 —— 见后端 domain/storage_cleanup。 */
export function storageOrphansQuery() {
  return {
    queryKey: ["admin", "storage-orphans"] as const,
    queryFn: () => api<StorageOrphans>("/api/admin/storage/orphans"),
  };
}

/** 删掉勾选的那些孤儿。后端删之前再判一遍,不再是孤儿的跳过。 */
export function deleteStorageOrphans(keys: string[]): Promise<components["schemas"]["StorageOrphanDeleteOut"]> {
  return api("/api/admin/storage/orphans/delete", { method: "POST", body: JSON.stringify({ keys }) });
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

/** 部署的网页地址(成员用浏览器打开 Mosael 的地方);空串 = 没有网页版。 */
export function setWebUrl(url: string): Promise<{ url: string }> {
  return api<{ url: string }>("/api/admin/web-url", { method: "PUT", body: JSON.stringify({ url }) });
}

/** 不带工作区的邀请(含升级前发出去的注册邀请码)。 */
export function deploymentInvites(): Promise<InviteLink[]> {
  return api<InviteLink[]>("/api/admin/invite-links");
}

/** 作废一张还没用过的不带工作区的邀请。 */
export function revokeDeploymentInvite(linkId: string): Promise<void> {
  return api<void>(`/api/admin/invite-links/${encodeURIComponent(linkId)}`, { method: "DELETE" });
}

export function createDeploymentInvite(note: string): Promise<IssuedInviteLink> {
  return api<IssuedInviteLink>("/api/admin/invite-links", { method: "POST", body: JSON.stringify({ note }) });
}

/** 工作区管理员请你放行的邀请链接(放行之后,还没账号的人也能凭它注册)。 */
export function invitesAwaitingSignup(): Promise<InviteLink[]> {
  return api<InviteLink[]>("/api/admin/invite-links/awaiting-signup");
}

export function approveInviteSignup(linkId: string): Promise<InviteLink> {
  return api<InviteLink>(`/api/admin/invite-links/${encodeURIComponent(linkId)}/approve-signup`, { method: "POST" });
}

/** 打开链接、还没登录时问一声:进哪个工作区、谁邀请的、还能不能用。码放在请求体里(地址会进访问日志)。 */
export function previewInviteLink(code: string): Promise<InviteLinkPreview> {
  return api<InviteLinkPreview>("/api/auth/invite-links/preview", { method: "POST", body: JSON.stringify({ code }) });
}

/** 已登录的人凭链接加入工作区。对用过它的那个人是幂等的(注册时已经凭它进来了也照样回那个工作区)。 */
export function redeemInviteLink(code: string): Promise<InviteLinkJoined> {
  return api<InviteLinkJoined>("/api/invite-links/redeem", { method: "POST", body: JSON.stringify({ code }) });
}

/** 第三方登录走到哪了:`waiting` / `confirm`(浏览器那边成了,等人填确认码)/ `error` / `expired`。从不带令牌。 */
export function oauthPending(pendingId: string): Promise<{ status: string; error?: string }> {
  return api(`/api/auth/oauth/pending/${pendingId}`);
}

/** 填回调页上的确认码。对上了交回令牌(一次性);填错了说还能试几次。 */
export function oauthConfirm(
  pendingId: string,
  code: string,
): Promise<{ status: string; token?: string; user?: User; error?: string; attempts_left?: number }> {
  return api(`/api/auth/oauth/pending/${pendingId}/confirm`, { method: "POST", body: JSON.stringify({ code }) });
}
