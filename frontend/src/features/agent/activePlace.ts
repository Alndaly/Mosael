/**
 * 「这个窗口眼下在哪」—— 页面说了算(ADR 0044 §3、§6)。
 *
 * **登记。** 每个有助手面板的页面在**页面那一层**调 `useAgentPlace(place)`(不是面板那一层:面板收起来时,免提浮标和
 * 智能体带你去也要知道你在哪),返回同一个 `place` 交给 `CanvasAgentChat`。登记处是一个模块级的栈,后挂上的在上面 ——
 * 工作台盖在页面上时是工作台,关了退回页面;栈空就是 AI Studio(素材、发布、设置这些没有面板的页面)。`useActivePlace()`
 * 读栈顶,浮标和跳转用它。不在 App 里另写一张「哪个视图 + id 对应哪个地方」的表:地方由页面自己说。
 *
 * **接力棒(拍板 6)。** 智能体在对话中途 `open_view` 带你去哪,那一处就接上这段对话 —— 你自己点过去的,面板显示那一处自己的。
 * 分得开靠的是:跳之前 `passConversation` 记一根棒子,跳过去之后**第一个变成「眼下这一处」的地方**接住它
 * (`adoptAgentSession`,只写那一处的选择、不碰家)。几种情形:
 *
 * - 落到一样具体的东西上(笔记、项目、画板、工作台那张……)—— 当场接住;
 * - 落到 AI Studio(没有面板的页面、笔记页没开哪篇)—— 等一小会儿(`SETTLE_MS`)再接:换页时旧页面先卸、新页面后挂
 *   (要加载的页面还得等它那一块代码),中间那一下栈是空的,不能让 AI Studio 抢走本该是笔记的那根棒子;
 * - 跳到原地(已经在那篇笔记里)—— 什么都没变(`NO_CHANGE_MS`),或者绕一圈又回到原处,棒子作废,免得你接下来自己
 *   点开别处时被它接走;
 * - 10 秒还没人接就作废。
 */

import React from "react";

import { STUDIO_PLACE, placeFromKey, placeKey, type AgentPlace } from "@/features/agent/places";
import { adoptAgentSession } from "@/features/agent/sessionSelection";

/** 落到 AI Studio 时等多久再接:等新页面挂上来、说出自己在哪。 */
const SETTLE_MS = 1200;
/** 跳完这么久登记处还一动没动:跳到了原地,棒子作废。 */
const NO_CHANGE_MS = 1500;
/** 棒子最长有效多久。 */
const BATON_MS = 10_000;

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
  if (baton) {
    baton.sawChange = true;
    // 等这一次提交里的卸载、挂载都做完再看(同一次提交里旧页面先卸、新页面后挂)。
    queueMicrotask(catchBaton);
  }
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

// —— 接力棒 ——

interface Baton {
  workspaceId: string;
  sessionId: string;
  /** 跳之前在哪:登记处还停在这里就不算跳过去了。 */
  from: string;
  sawChange: boolean;
  timers: number[];
}

let baton: Baton | null = null;

function dropBaton() {
  if (!baton) return;
  for (const timer of baton.timers) window.clearTimeout(timer);
  baton = null;
}

function handOver(key: string) {
  if (!baton) return;
  adoptAgentSession(baton.workspaceId, placeFromKey(key), baton.sessionId);
  dropBaton();
}

function catchBaton() {
  if (!baton) return;
  const key = activeKey();
  if (key !== STUDIO_KEY && key !== baton.from) {
    handOver(key);
    return;
  }
  //: 落在 AI Studio 上,或者绕了一圈又回到原处:等新页面挂稳了再定。
  const waiting = baton;
  waiting.timers.push(window.setTimeout(() => {
    if (baton !== waiting) return;
    const settled = activeKey();
    if (settled === waiting.from) dropBaton();
    else if (settled === STUDIO_KEY) handOver(STUDIO_KEY);
  }, SETTLE_MS));
}

/**
 * 智能体要带你去别处了:这段对话跟过去(见文件头)。跳之前调。同一个窗口同时只有一根棒子 —— 新的取代旧的。
 */
export function passConversation(workspaceId: string, sessionId: string): void {
  dropBaton();
  const next: Baton = { workspaceId, sessionId, from: activeKey(), sawChange: false, timers: [] };
  baton = next;
  next.timers.push(
    window.setTimeout(() => {
      if (baton === next && !next.sawChange) dropBaton();
    }, NO_CHANGE_MS),
    window.setTimeout(() => {
      if (baton === next) dropBaton();
    }, BATON_MS),
  );
}

/** 测试用:清空登记处和接力棒。 */
export function resetActivePlaces(): void {
  entries.length = 0;
  dropBaton();
}
