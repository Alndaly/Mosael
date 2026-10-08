import type { components } from "@/api/generated/schema";
import { api, apiStream } from "@/api/transport";

export type SessionGroup = components["schemas"]["SessionGroupOut"];
export type SessionGroupKind = "agent" | "generation";

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
/** 消息带着的一段笔记摘录(笔记页的选区),落进 payload.quote,气泡里画成可点的一行。 */
export type AgentMessageQuote = components["schemas"]["AgentMessageQuoteIn"];

/** 一处地方(ADR 0044):种类加那样东西的 id。会话的家、每条消息在哪说的都是它。 */
export type AgentPlaceIn = components["schemas"]["PlaceIn"];

/** 不给 `home` 列整个工作区的(AI Studio);给了只列家在那里的(各处面板的「这里的对话」)。 */
export const listAgentSessions = (workspaceId: string, home?: { kind: string; id: string }) => {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (home) {
    params.set("home_kind", home.kind);
    params.set("home_id", home.id);
  }
  return api<AgentSession[]>(`/api/agent/sessions?${params.toString()}`);
};
/** ComfyUI 那张存盘、改名、挪文件夹时,家跟着挪(ADR 0044 §9)。只收 `comfyui`,只挪自己的;回挪了几段。 */
export const moveAgentHomes = (body: components["schemas"]["AgentHomesMove"]) =>
  api<components["schemas"]["AgentHomesMoved"]>("/api/agent/homes/move", { method: "POST", body: JSON.stringify(body) });
/** 建会话的请求体。标题不给:后端先记一个占位,第一句话进来时起名(见 host.post_user_message)。 */
export type AgentSessionCreateBody = Omit<components["schemas"]["AgentSessionCreate"], "title">;
export const createAgentSession = (body: AgentSessionCreateBody) =>
  api<AgentSession>("/api/agent/sessions", { method: "POST", body: JSON.stringify(body) });
export const getAgentSession = (sessionId: string) => api<AgentSession>(`/api/agent/sessions/${sessionId}`);
export const updateAgentSession = (sessionId: string, body: Record<string, unknown>) =>
  api<AgentSession>(`/api/agent/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(body) });
/** 「本会话始终允许」加一条:后端在它那一份上合并(界面不再读出整份、加一条、写回去 —— 两张卡同时点会丢一条)。 */
export const addSessionAllowance = (sessionId: string, body: components["schemas"]["SessionAllowance"]) =>
  api<AgentSession>(`/api/agent/sessions/${sessionId}/allowances`, { method: "POST", body: JSON.stringify(body) });

export const listAgentMessages = (sessionId: string) =>
  api<AgentMessage[]>(`/api/agent/sessions/${sessionId}/messages`);
export const sendAgentMessage = (sessionId: string, body: Record<string, unknown>) =>
  api<AgentMessage>(`/api/agent/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify(body) });
/** 正在进行的这一回合的增量(SSE)。每条 data 是一份 `AgentStreamEvent`,见 features/agent/useAgentTurnStream。 */
export const streamAgentTurn = (sessionId: string, signal: AbortSignal) =>
  apiStream(`/api/agent/sessions/${sessionId}/stream`, { signal });
export const stopAgentSession = (sessionId: string) =>
  api(`/api/agent/sessions/${sessionId}/stop`, { method: "POST" });
export const compactAgentSession = <T>(sessionId: string) =>
  api<T>(`/api/agent/sessions/${sessionId}/compact`, { method: "POST" });

/** 智能体在对话里问人的那几张卡(选择题 / 自由文本),答了或跳过它才往下走。 */
export type AgentQuestion = components["schemas"]["AgentQuestionOut"];
export const listAgentQuestions = (sessionId: string) =>
  api<AgentQuestion[]>(`/api/agent/questions?session_id=${encodeURIComponent(sessionId)}`);
export const answerAgentQuestion = (questionId: string, answers: Record<string, string[]>) =>
  api(`/api/agent/questions/${questionId}/answer`, { method: "POST", body: JSON.stringify({ answers }) });
export const dismissAgentQuestion = (questionId: string) =>
  api(`/api/agent/questions/${questionId}/dismiss`, { method: "POST" });

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
