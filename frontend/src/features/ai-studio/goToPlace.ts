/**
 * 「回到那里」:在一段对话的家那一处接着它,再跳到那一页(ADR 0044 §5)。AI Studio 的每一行、右上角全局确认卡上那一行用它。
 *
 * 先写那一处的选择(`adoptAgentSession`,不碰家),再跳:跳过去的面板一挂上就是这段对话。剪辑、笔记、画板、工作流、场景走
 * 现有的深链;ComfyUI 的打开工作台、打开那一张(存过的才回得去 —— 没存过的标签页关了就回不去了,见 homeLabel.canGoHome)。
 */

import { listPluginPackages, getWorkflowLibrary } from "@/api/client";
import { adoptAgentSession } from "@/features/agent/currentAgentSession";
import { comfyParts, homeOf, type AgentPlace } from "@/features/agent/places";
import type { SessionHome } from "@/features/agent/homeLabel";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";
import { VIEW_RECORD_EVENTS, gotoRecord, openBoard, openNote } from "@/lib/deepLink";

async function openComfy(workspaceId: string, placeId: string): Promise<void> {
  const { connection, path } = comfyParts(placeId);
  const [library, packages] = await Promise.all([getWorkflowLibrary(connection, workspaceId), listPluginPackages()]);
  const editor = library.editor;
  if (!editor || editor.kind !== "comfyui" || !workbenchAvailable()) throw new Error("workbench unavailable");
  const instance = packages.flatMap((one) => one.instances ?? []).find((one) => one.id === connection);
  const opened = await openWorkbench(
    { instanceId: connection, instanceName: instance?.name ?? "", workspaceId, url: editor.url },
    path ? { path } : {},
  );
  if (!opened.ok) throw new Error(opened.error || "workbench failed");
}

export function goToPlace(workspaceId: string, place: AgentPlace): Promise<void> | void {
  switch (place.kind) {
    case "studio":
      window.location.hash = "#/ai";
      return;
    case "project":
      gotoRecord(`/editor?p=${encodeURIComponent(place.id)}`);
      return;
    case "note":
      openNote(place.id);
      return;
    case "board":
      //: 走信箱,不只改 hash:人已经在画板页上时只改 hash 没反应(见 lib/deepLink 的 openBoard)。
      openBoard(place.id);
      return;
    case "workflow":
      gotoRecord("/workflows", VIEW_RECORD_EVENTS.workflows, place.id);
      return;
    case "scene":
      window.location.hash = `#/scenes?scene=${encodeURIComponent(place.id)}`;
      return;
    case "comfyui":
      return openComfy(workspaceId, place.id);
  }
}

/** 在它的家那一处接着这段对话,再跳过去。 */
export function goHome(workspaceId: string, session: SessionHome & { id: string }): Promise<void> | void {
  const home = homeOf(session);
  adoptAgentSession(workspaceId, home, session.id);
  return goToPlace(workspaceId, home);
}
