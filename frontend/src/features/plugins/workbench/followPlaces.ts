/**
 * 工作台里的对话跟着画布上的那一张走(ADR 0044 §6、§9)。桥和主进程只报一次的两种消息(见 workbenchSession 的
 * `onWorkbenchPlaces`):
 *
 * - **同一张换了地方**(在 ComfyUI 里第一次存盘、改名、挪文件夹):这一处的选择当场挪过去,家在后端挪(`moveAgentPlace`)。
 *   「另存为」是新的一张、新的一处,桥不报,对话留在原来那张;
 * - **智能体在新标签页开了一张**(`comfy_canvas_new`,主进程报回是哪段对话开的):新标签页那一处接住这段对话 —— 不靠
 *   `pending_view`:新标签页一出现「眼下这一处」就换了,那条路会接不着。
 *
 * 先接住、再挪:同一批里两样都有时,新开的那张随后被存盘,对话跟着它挪到存好的地方。
 */
import React from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { adoptAgentSession, moveAgentPlace } from "@/features/agent/currentAgentSession";
import { comfyPlace } from "@/features/agent/places";
import { onWorkbenchPlaces, type WorkbenchPlaceNews } from "@/features/plugins/workbench/workbenchSession";

export function followWorkbenchPlaces(qc: QueryClient, news: WorkbenchPlaceNews): void {
  const { instanceId, workspaceId } = news.target;
  if (news.openedBy) {
    adoptAgentSession(workspaceId, comfyPlace(instanceId, news.openedBy.workflow), news.openedBy.sessionId);
  }
  for (const { from, to } of news.renames) {
    // 后端没挪成(断网):那几段留在旧地方、出现在「其他对话」里 —— 不丢,也不值得打断画布上的事
    moveAgentPlace(qc, workspaceId, comfyPlace(instanceId, from), comfyPlace(instanceId, to)).catch(() => undefined);
  }
}

/** 工作台挂着的时候听着(只有一个工作台)。 */
export function useFollowWorkbenchPlaces(): void {
  const qc = useQueryClient();
  React.useEffect(() => onWorkbenchPlaces((news) => followWorkbenchPlaces(qc, news)), [qc]);
}
