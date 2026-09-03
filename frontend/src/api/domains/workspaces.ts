import type { components } from "@/api/generated/schema";
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

export function createWorkspace(name: string): Promise<Workspace> {
  return api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) });
}

export function renameWorkspace(workspaceId: string, name: string): Promise<{ id: string; name: string }> {
  return api(`/api/workspaces/${workspaceId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteWorkspace(workspaceId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}`, { method: "DELETE" });
}

export function workspaceSummary(workspaceId: string): Promise<WorkspaceSummary> {
  return api<WorkspaceSummary>(`/api/workspaces/${workspaceId}/summary`);
}

export function renameProject(projectId: string, name: string): Promise<Project> {
  return api<Project>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteProject(projectId: string): Promise<unknown> {
  return api(`/api/projects/${projectId}`, { method: "DELETE" });
}
