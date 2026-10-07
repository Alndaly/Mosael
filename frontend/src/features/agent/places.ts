/**
 * 地方:界面上的每一处、一段对话的家、每条消息在哪说的,都是这同一个形状 —— 一个种类加一个 id(ADR 0044 §1,后端是
 * domain/agent/places)。
 *
 * | 种类 | id |
 * | --- | --- |
 * | `studio` | 空(AI Studio,以及页面上没打开哪样东西的时候) |
 * | `project` / `note` / `board` / `workflow` / `scene` | 那样东西的 id |
 * | `comfyui` | `<连接 id>/<路径>`(存过的)、`<连接 id>#<标签页 key>`(没存过的)、`<连接 id>`(画布上一张都没开) |
 *
 * 连接 id 里没有 `/`、`#`,从左边第一个 `/` 或 `#` 切开就分得清。
 */

import type { components } from "@/api/generated/schema";

export type AgentPlaceKind = components["schemas"]["PlaceIn"]["kind"];

export interface AgentPlace {
  readonly kind: AgentPlaceKind;
  readonly id: string;
}

export const STUDIO_PLACE: AgentPlace = Object.freeze({ kind: "studio", id: "" });

/** 一处地方的键:选择存在哪、清单缓存在哪。`studio`、`note:<id>`、`comfyui:<连接>/<路径>`…… */
export function placeKey(place: AgentPlace): string {
  return place.kind === "studio" ? "studio" : `${place.kind}:${place.id}`;
}

export function placeFromKey(key: string): AgentPlace {
  const cut = key.indexOf(":");
  if (cut < 0) return STUDIO_PLACE;
  return { kind: key.slice(0, cut) as AgentPlaceKind, id: key.slice(cut + 1) };
}

export function samePlace(a: AgentPlace, b: AgentPlace): boolean {
  return a.kind === b.kind && a.id === b.id;
}

/** 一段对话的家。 */
export function homeOf(session: { home_kind: AgentPlaceKind; home_id: string }): AgentPlace {
  return { kind: session.home_kind, id: session.home_id };
}

/** 消息体里的 `place`(只给形状,不带别的)。 */
export function placePayload(place: AgentPlace): { kind: AgentPlaceKind; id: string } {
  return { kind: place.kind, id: place.id };
}

/** ComfyUI 的地方 id 切成三段:连接、存过的路径、没存过的标签页 key(后两样至多一样不空)。 */
export function comfyParts(placeId: string): { connection: string; path: string; key: string } {
  const marks = [placeId.indexOf("/"), placeId.indexOf("#")].filter((index) => index >= 0);
  if (marks.length === 0) return { connection: placeId, path: "", key: "" };
  const cut = Math.min(...marks);
  const rest = placeId.slice(cut + 1);
  return placeId[cut] === "/"
    ? { connection: placeId.slice(0, cut), path: rest, key: "" }
    : { connection: placeId.slice(0, cut), path: "", key: rest };
}

/**
 * 工作台里的那一处:这台 ComfyUI + 画布上开着的那张。存过的认路径,没存过的认标签页的 key,一张都没开就是连接本身 ——
 * 在那里要新建工作流,得有 ComfyUI 那份工具(ADR 0044 §8)。换标签页就是换地方。
 */
export function comfyPlace(connectionId: string, workflow: { path?: string | null; key?: string | null } | null | undefined): AgentPlace {
  if (workflow?.path) return { kind: "comfyui", id: `${connectionId}/${workflow.path}` };
  if (workflow?.key) return { kind: "comfyui", id: `${connectionId}#${workflow.key}` };
  return { kind: "comfyui", id: connectionId };
}
