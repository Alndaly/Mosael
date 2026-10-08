import type { components } from "@/api/generated/schema";
import type { InviteLink, IssuedInviteLink } from "@/api/domains/identity";
import { api } from "@/api/transport";

export type Workspace = components["schemas"]["WorkspaceOut"];
export type WorkspaceMember = components["schemas"]["WorkspaceMemberOut"] & { display_name: string };
export type MembersInfo = Omit<components["schemas"]["MembersOut"], "members"> & {
  members: WorkspaceMember[];
};
export type WorkspaceInvitation = components["schemas"]["InvitationOut"];
export type WorkspaceSummary = components["schemas"]["WorkspaceSummaryOut"];
export type Project = components["schemas"]["ProjectOut"];
export type ProjectWithStats = components["schemas"]["ProjectWithStatsOut"];

export function listMembers(workspaceId: string): Promise<MembersInfo> {
  return api<MembersInfo>(`/api/workspaces/${workspaceId}/members`);
}

export function inviteMember(
  workspaceId: string,
  body: { username: string; role: string },
): Promise<WorkspaceInvitation> {
  return api<WorkspaceInvitation>(`/api/workspaces/${workspaceId}/invitations`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** 这个工作区发出去、对方还没应答的邀请(团队页列在成员下面)。 */
export function sentInvitations(workspaceId: string): Promise<{ invitations: WorkspaceInvitation[] }> {
  return api<{ invitations: WorkspaceInvitation[] }>(`/api/workspaces/${workspaceId}/invitations`);
}

/** 发一张进这个工作区的邀请链接(ADR 0054):7 天、一次性。原文只在回来的这一次。 */
export function createWorkspaceInviteLink(workspaceId: string, role: string): Promise<IssuedInviteLink> {
  return api<IssuedInviteLink>(`/api/workspaces/${workspaceId}/invite-links`, { method: "POST", body: JSON.stringify({ role }) });
}

/** 这个工作区发出去、还能用的邀请链接。 */
export function workspaceInviteLinks(workspaceId: string): Promise<InviteLink[]> {
  return api<InviteLink[]>(`/api/workspaces/${workspaceId}/invite-links`);
}

export function revokeWorkspaceInviteLink(workspaceId: string, linkId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}/invite-links/${linkId}`, { method: "DELETE" });
}

/** 请部署管理员放行:让还没账号的人也能凭这张链接注册。 */
export function requestInviteSignup(workspaceId: string, linkId: string): Promise<InviteLink> {
  return api<InviteLink>(`/api/workspaces/${workspaceId}/invite-links/${linkId}/request-signup`, { method: "POST" });
}

export function revokeInvitation(workspaceId: string, invitationId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}/invitations/${invitationId}`, { method: "DELETE" });
}

export function myInvitations(): Promise<{ invitations: WorkspaceInvitation[] }> {
  return api<{ invitations: WorkspaceInvitation[] }>("/api/invitations");
}

export function respondInvitation(invitationId: string, accept: boolean): Promise<WorkspaceInvitation> {
  return api<WorkspaceInvitation>(`/api/invitations/${invitationId}/${accept ? "accept" : "decline"}`, {
    method: "POST",
  });
}

export function setMemberRole(workspaceId: string, userId: string, role: string): Promise<WorkspaceMember> {
  return api<WorkspaceMember>(`/api/workspaces/${workspaceId}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeMember(workspaceId: string, userId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
}

export function listWorkspaces(): Promise<Workspace[]> {
  return api<Workspace[]>("/api/workspaces");
}

export function createWorkspace(name: string): Promise<Workspace> {
  return api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) });
}

export function renameWorkspace(workspaceId: string, name: string): Promise<{ id: string; name: string }> {
  return api(`/api/workspaces/${workspaceId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteWorkspace(workspaceId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}`, { method: "DELETE" });
}

export function workspaceSummary(workspaceId: string, days: number): Promise<WorkspaceSummary> {
  return api<WorkspaceSummary>(`/api/workspaces/${workspaceId}/summary?days=${days}`);
}

export function renameProject(projectId: string, name: string): Promise<Project> {
  return api<Project>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteProject(projectId: string): Promise<unknown> {
  return api(`/api/projects/${projectId}`, { method: "DELETE" });
}
