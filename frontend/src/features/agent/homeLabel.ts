/**
 * 「在剪辑《A》里开的」—— 一段对话的家说成一句人话(ADR 0044 §10)。AI Studio 的每一行、面板下拉里「其他对话」的每一行、
 * 面板标题下那一行、右上角全局确认卡上那一行,都是这一个函数。
 *
 * 名字是后端**按看的人**现查的(`home_name`):家删了是 `deleted`、他看不见是 `hidden`,这两种 `home_name` 是空串 ——
 * 于是只说「在一篇笔记里开的」,不会把他看不见的标题写出来。
 */

import type { MessageKey } from "@/app/messages";
import type { useI18n } from "@/app/preferences";
import { comfyParts, type AgentPlaceKind } from "@/features/agent/places";

type Translate = ReturnType<typeof useI18n>;

export interface SessionHome {
  home_kind: AgentPlaceKind;
  home_id: string;
  home_name: string;
  home_state: "ok" | "deleted" | "hidden";
}

const NAMED: Record<Exclude<AgentPlaceKind, "studio" | "comfyui">, MessageKey> = {
  project: "agentPlaceProject",
  note: "agentPlaceNote",
  board: "agentPlaceBoard",
  workflow: "agentPlaceWorkflow",
  scene: "agentPlaceScene",
};
const DELETED: Record<Exclude<AgentPlaceKind, "studio">, MessageKey> = {
  project: "agentPlaceDeletedProject",
  note: "agentPlaceDeletedNote",
  board: "agentPlaceDeletedBoard",
  workflow: "agentPlaceDeletedWorkflow",
  scene: "agentPlaceDeletedScene",
  comfyui: "agentPlaceDeletedComfy",
};
const HIDDEN: Record<Exclude<AgentPlaceKind, "studio">, MessageKey> = {
  project: "agentPlaceHiddenProject",
  note: "agentPlaceHiddenNote",
  board: "agentPlaceHiddenBoard",
  workflow: "agentPlaceHiddenWorkflow",
  scene: "agentPlaceHiddenScene",
  comfyui: "agentPlaceHiddenComfy",
};

/** 那一处叫什么:「剪辑《A》」「已删除的笔记」「一台 ComfyUI」…… */
export function placeName(t: Translate, home: SessionHome): string {
  if (home.home_kind === "studio") return t("agentPlaceStudio");
  if (home.home_state === "deleted") return t(DELETED[home.home_kind]);
  if (home.home_state === "hidden") return t(HIDDEN[home.home_kind]);
  if (home.home_kind === "comfyui") {
    const { path, key } = comfyParts(home.home_id);
    const kind: MessageKey = path ? "agentPlaceComfySaved" : key ? "agentPlaceComfyUnsaved" : "agentPlaceComfyConnection";
    return t(kind).replace("{name}", home.home_name);
  }
  const name = home.home_name || (home.home_kind === "note" ? t("documentUntitled") : "");
  return t(NAMED[home.home_kind]).replace("{name}", name);
}

/** AI Studio 的行上、「其他对话」的行上那一句:「在剪辑《A》里开的」。 */
export function openedIn(t: Translate, home: SessionHome): string {
  return t("agentOpenedIn").replace("{place}", placeName(t, home));
}

/** 面板标题下那一行(当前这段的家不在这里时):「这段对话是在剪辑《A》里开的」。 */
export function thisWasOpenedIn(t: Translate, home: SessionHome): string {
  return t("agentThisWasOpenedIn").replace("{place}", placeName(t, home));
}

/**
 * 「回到那里」去得了吗:家删了、看不见、在 AI Studio(本来就在这儿),或者是一张没存过的 ComfyUI 标签页(关了就回不去了),
 * 都不给这颗。
 */
export function canGoHome(home: SessionHome): boolean {
  if (home.home_kind === "studio" || home.home_state !== "ok") return false;
  return home.home_kind !== "comfyui" || !comfyParts(home.home_id).key;
}
