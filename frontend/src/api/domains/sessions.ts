import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type SessionGroup = components["schemas"]["SessionGroupOut"];
export type SessionGroupKind = "agent" | "generation";

export interface CapabilityModel {
  provider_profile_id: string;
  provider_name: string;
  model: string;
  display_name: string;
}

export function listSessionGroups(workspaceId: string, kind: SessionGroupKind): Promise<SessionGroup[]> {
  return api<SessionGroup[]>(`/api/session-groups?workspace_id=${workspaceId}&kind=${kind}`);
}

export function createSessionGroup(
  workspaceId: string,
  kind: SessionGroupKind,
  name: string,
): Promise<SessionGroup> {
  return api<SessionGroup>("/api/session-groups", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, kind, name }),
  });
}

export function renameSessionGroup(groupId: string, name: string): Promise<SessionGroup> {
  return api<SessionGroup>(`/api/session-groups/${groupId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

/** Deleting a group leaves its sessions ungrouped. */
export function deleteSessionGroup(groupId: string): Promise<unknown> {
  return api(`/api/session-groups/${groupId}`, { method: "DELETE" });
}

export function deleteAgentSession(sessionId: string): Promise<unknown> {
  return api(`/api/agent/sessions/${sessionId}`, { method: "DELETE" });
}

export function listCapabilityModels(
  capability: string,
  surface: "all" | "agent" | "direct" | "gateway" | "automation" = "all",
): Promise<CapabilityModel[]> {
  return api<CapabilityModel[]>(`/api/settings/capability-models/${capability}?surface=${surface}`);
}

/** Share or unshare a user-owned resource with one workspace. */
export function setResourceShared(
  kind: "publish_account" | "browser_profile" | "agent_session" | "generation_session" | "scheduled_task",
  resourceId: string,
  workspaceId: string,
  shared: boolean,
): Promise<{ workspaces: string[] }> {
  return api(`/api/shares/${kind}/${resourceId}`, {
    method: shared ? "POST" : "DELETE",
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}
