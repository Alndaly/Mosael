/**
 * 「这个窗口眼下在哪」—— 页面说了算(ADR 0044 §3)。
 *
 * **登记。** 每个有助手面板的页面在**页面那一层**调 `useAgentPlace(place)`(不是面板那一层:面板收起来时,免提浮标也要
 * 知道你在哪),返回同一个 `place` 交给 `CanvasAgentChat`。登记处是一个模块级的栈,后挂上的在上面 —— 工作台盖在页面上时
 * 是工作台,关了退回页面;栈空就是 AI Studio(素材、发布、设置这些没有面板的页面)。`useActivePlace()` 读栈顶,浮标用它。
 * 不在 App 里另写一张「哪个视图 + id 对应哪个地方」的表:地方由页面自己说。
 *
 * 换了地方不改任何一处的选择:你点到哪,面板就显示那一处自己的对话。
 */

import React from "react";

import { STUDIO_PLACE, placeFromKey, placeKey, type AgentPlace } from "@/features/agent/places";

const STUDIO_KEY = placeKey(STUDIO_PLACE);

interface Entry {
  token: symbol;
  /** 空串 = 这个页面还没说出自己在哪(刚挂上那一下)。 */
  key: string;
}

const entries: Entry[] = [];
const listeners = new Set<() => void>();

function activeKey(): string {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    if (entries[index].key) return entries[index].key;
  }
  return STUDIO_KEY;
}

function changed() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * 页面说自己在哪,返回同一个 `place`(交给 `CanvasAgentChat`)。`null` = 这个页面这会儿不登记(工作台还没连上哪台
 * ComfyUI)。地方变了(换一篇笔记、工作台换标签页)原地改,不挪位置 —— 盖在上面的工作台还在上面。
 */
export function useAgentPlace(place: AgentPlace): AgentPlace;
export function useAgentPlace(place: AgentPlace | null): AgentPlace | null;
export function useAgentPlace(place: AgentPlace | null): AgentPlace | null {
  const token = React.useRef<symbol | null>(null);
  const key = place ? placeKey(place) : "";
  React.useEffect(() => {
    const mine = Symbol("agent-place");
    token.current = mine;
    entries.push({ token: mine, key: "" });
    return () => {
      const index = entries.findIndex((entry) => entry.token === mine);
      if (index >= 0) entries.splice(index, 1);
      changed();
    };
  }, []);
  React.useEffect(() => {
    const entry = entries.find((one) => one.token === token.current);
    if (!entry || entry.key === key) return;
    entry.key = key;
    changed();
  }, [key]);
  //: 同一处给同一个对象:页面每次渲染都新写一个字面量,面板不该因此当成换了地方。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return React.useMemo(() => place, [key]);
}

/** 这个窗口眼下在哪:最上面那个登记了的页面;都没有就是 AI Studio。 */
export function useActivePlace(): AgentPlace {
  const key = React.useSyncExternalStore(subscribe, activeKey);
  return React.useMemo(() => placeFromKey(key), [key]);
}

/** 测试用:清空登记处。 */
export function resetActivePlaces(): void {
  entries.length = 0;
}
