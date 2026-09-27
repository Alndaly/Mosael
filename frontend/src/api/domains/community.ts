import { api } from "@/api/transport";
import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";

/**
 * 社区(ADR 0026):我的社区账号(设备授权)、画板分享、发布到社区。
 *
 * 前端从不碰社区的令牌 —— 本机后端替你拿着刷新令牌、替你续期,这里只问「连没连、连的是谁」。
 */
export type CommunityStatus = components["schemas"]["CommunityStatusOut"];
export type CommunityDevice = components["schemas"]["CommunityDeviceOut"];
export type CommunityPoll = components["schemas"]["CommunityPollOut"];
export type CommunityUrl = components["schemas"]["CommunityUrlOut"];
export type BoardShare = components["schemas"]["BoardShareOut"];
export type BoardShareState = components["schemas"]["BoardShareStateOut"];
export type BoardShareVisibility = components["schemas"]["BoardShareIn"]["visibility"];
export type CommunityPublishResult = components["schemas"]["CommunityPublishOut"];
export type WorkflowPublishRequest = components["schemas"]["WorkflowPublishIn"];
export type PluginPublishRequest = components["schemas"]["PluginPublishIn"];

export const getCommunityStatus = () => api<CommunityStatus>("/api/community/status");
export const startCommunityConnect = () => api<CommunityDevice>("/api/community/connect", { method: "POST" });
export const pollCommunityConnect = () => api<CommunityPoll>("/api/community/connect/poll", { method: "POST" });
export const cancelCommunityConnect = () => api<void>("/api/community/connect", { method: "DELETE" });
export const disconnectCommunity = () => api<void>("/api/community/disconnect", { method: "POST" });

/** 部署设置:这台后端连哪个社区。读谁都能读,改要部署管理员。 */
export const getCommunityUrl = () => api<CommunityUrl>("/api/admin/community");
export const setCommunityUrl = (url: string) =>
  api<CommunityUrl>("/api/admin/community", { method: "PUT", body: JSON.stringify({ url }) });

export const getBoardShare = (boardId: string, workspaceId: string) =>
  api<BoardShareState>(`/api/boards/${boardId}/share?workspace_id=${encodeURIComponent(workspaceId)}`);
/** 生成链接 / 更新分享:排一个任务,链接在任务做完之后出现在分享面板里。 */
export const shareBoard = (
  boardId: string,
  body: { workspace_id: string; title: string; visibility: BoardShareVisibility },
) => api<Job>(`/api/boards/${boardId}/share`, { method: "POST", body: JSON.stringify(body) });
export const updateBoardShare = (
  boardId: string,
  body: { workspace_id: string; title?: string; visibility?: BoardShareVisibility },
) => api<BoardShare>(`/api/boards/${boardId}/share`, { method: "PATCH", body: JSON.stringify(body) });
export const withdrawBoardShare = (boardId: string, workspaceId: string) =>
  api<void>(`/api/boards/${boardId}/share?workspace_id=${encodeURIComponent(workspaceId)}`, { method: "DELETE" });

export const publishWorkflowToCommunity = (workflowId: string, body: WorkflowPublishRequest) =>
  api<CommunityPublishResult>(`/api/workflows/${workflowId}/community`, { method: "POST", body: JSON.stringify(body) });
export const publishPluginToCommunity = (packageId: string, body: PluginPublishRequest) =>
  api<CommunityPublishResult>(`/api/plugins/${encodeURIComponent(packageId)}/community`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/** 社区网站上「我的提交」「我的分享」两页的地址(站点根 + 路径)。 */
export function communityPage(origin: string, page: "submissions" | "shares"): string {
  return `${origin.replace(/\/+$/, "")}/me/${page}`;
}
