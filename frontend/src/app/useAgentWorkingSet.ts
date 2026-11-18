import React from "react";

import { useCurrentAgentSession, useSessionSettings } from "@/features/agent/currentAgentSession";
import type { AgentPlace, AgentPlaceKind } from "@/features/agent/places";
import type { components } from "@/api/generated/schema";

export const STUDIO_PLACE: AgentPlace = Object.freeze({ kind: "studio", id: "" });

const SURFACE_BY_PLACE: Record<AgentPlaceKind, components["schemas"]["AgentWorkingSet"]["surface"]> = {
  studio: "ai",
  project: "editor",
  note: "notes",
  board: "boards",
  workflow: "workflows",
  scene: "scenes",
  comfyui: "ai",
};

/**
 * 页面选区 → 会话 working_set 的同步点。
 *
 * **放在 lib 而不是 features/**:Notes / Media / Boards / Workflows 都由 Agent 的
 * 装配层挂进来,如果页面再直接 import Agent,就会和 Agent 的装配文件形成依赖环。
 * 这个 hook 只同步“当前指代”,不是会话归属,也不阻止 Agent 操作别的项目。
 */
export function useAgentWorkingSet(
  workspaceId: string,
  place: AgentPlace,
  selection: Record<string, unknown>,
  selectionKey: string,
) {
  const agentSession = useCurrentAgentSession(workspaceId, place).session;
  const { settings, update } = useSessionSettings(workspaceId, place, agentSession);
  const placeKey = `${place.kind}:${place.id}`;
  React.useEffect(() => {
    if (agentSession?.is_mine === false) return;
    update.mutate({
      working_set: {
        project_id: settings.working_set?.project_id ?? "",
        surface: SURFACE_BY_PLACE[place.kind],
        selection,
      },
    });
    // 选区只是“这个/这段”的指代,不是归属;不要在 effect 里依赖整个 selection 对象。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, placeKey, selectionKey, agentSession?.id]);
}
