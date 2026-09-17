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

// ---- 智能体对话 ----
//
// 路径只写在这里。对话壳(features/agent)和 AI 工作台两处都在调同一批接口,此前各自拼路径 ——
// 同一个端点在两边写法不同,改起来要满仓库找字符串。

export type AgentSession = components["schemas"]["AgentSessionOut"];
export type AgentMessage = components["schemas"]["AgentMessageOut"];

export const listAgentSessions = (workspaceId: string) =>
  api<AgentSession[]>(`/api/agent/sessions?workspace_id=${encodeURIComponent(workspaceId)}`);
export const createAgentSession = (body: Record<string, unknown>) =>
  api<AgentSession>("/api/agent/sessions", { method: "POST", body: JSON.stringify(body) });
export const getAgentSession = (sessionId: string) => api<AgentSession>(`/api/agent/sessions/${sessionId}`);
export const updateAgentSession = (sessionId: string, body: Record<string, unknown>) =>
  api<AgentSession>(`/api/agent/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(body) });

export const listAgentMessages = (sessionId: string) =>
  api<AgentMessage[]>(`/api/agent/sessions/${sessionId}/messages`);
export const sendAgentMessage = (sessionId: string, body: Record<string, unknown>) =>
  api<AgentMessage>(`/api/agent/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify(body) });
export const stopAgentSession = (sessionId: string) =>
  api(`/api/agent/sessions/${sessionId}/stop`, { method: "POST" });
export const compactAgentSession = <T>(sessionId: string) =>
  api<T>(`/api/agent/sessions/${sessionId}/compact`, { method: "POST" });

export const listAgentQueue = (sessionId: string) =>
  api<AgentMessage[]>(`/api/agent/sessions/${sessionId}/queue`);
export const dropQueuedMessage = (sessionId: string, messageId: string) =>
  api(`/api/agent/sessions/${sessionId}/queue/${messageId}`, { method: "DELETE" });
export const steerQueuedMessage = (sessionId: string, messageId: string) =>
  api<{ steered: boolean }>(`/api/agent/sessions/${sessionId}/queue/${messageId}/steer`, { method: "POST" });

export const listAgentUsageEvents = <T>(sessionId: string) =>
  api<T[]>(`/api/agent/sessions/${sessionId}/usage-events`);

export const agentManifest = <T>() => api<T>("/api/agent/manifest");
export const listAgentTools = <T>() => api<T[]>("/api/agent/tools");
