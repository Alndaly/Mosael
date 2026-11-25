import React from "react";

/**
 * 灵动岛上的**一件正在发生的事**(ADR 0111)。哪个功能知道这件事,哪个功能发布它;岛只负责摆,不认识任何一种。
 *
 * - `ongoing`:还在做(任务在跑):常驻,直到发布它的组件撤掉;
 * - `done` / `failed`:刚结束的那一下(任务做完了):亮几秒自己消失(`flashLiveActivity`)。
 *
 * 同一时刻可以有好几件:岛上平时只摆最要紧的一件(`priority` 大的在前,同级时新的在前),悬停展开看全部。
 * 实际显示在 macOS 原生 NSPanel 浮层里(见 electron/macos-island.cjs),不是 Mosael 窗口内的元素。
 */
export type LiveActivityState = "ongoing" | "done" | "failed";

export interface LiveActivity {
  /** 同一件事的 id:再发布一次就是更新它。 */
  id: string;
  state: LiveActivityState;
  /** 一句话:「生成图片」「3 个任务进行中」。 */
  title: string;
  /** 第二行:进度说明、结果。可空。 */
  detail?: string;
  /** 0..1;不知道就是 null(画不确定的转圈)。 */
  progress?: number | null;
  /** 这件事的图标(lucide 组件);原生层按状态画自己的记号,不序列化这个字段。 */
  icon: React.ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>;
  /** 越大越在前;缺省 0。 */
  priority?: number;
  /** 点它去哪(打开任务中心、跳到结果)。 */
  onOpen?: () => void;
}

interface Entry extends LiveActivity {
  /** 发布的先后:同级时新的在前。 */
  order: number;
}

/** 刚结束的那一下亮多久。 */
export const FLASH_MS = 4000;

let entries: Entry[] = [];
let sequence = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

/** 原生浮层是否可用:只有 macOS 的预加载桥提供这条通道。 */
export function liveActivityAvailable(): boolean {
  return typeof window !== "undefined" && window.mosaelDesktop?.platform === "darwin"
    && typeof window.mosaelDesktop.reportLiveActivities === "function";
}

/** 序列化成原生认识的形状。图标与点击回调不过进程边界。 */
function wireActivities(): Array<{ id: string; state: LiveActivityState; title: string; detail?: string; progress?: number; priority?: number }> {
  return entries.map(({ id, state, title, detail, progress, priority }) => ({
    id,
    state,
    title,
    ...(detail ? { detail } : {}),
    ...(typeof progress === "number" ? { progress } : {}),
    ...(priority === undefined ? {} : { priority }),
  }));
}

function sync(): void {
  if (!liveActivityAvailable()) return;
  window.mosaelDesktop?.reportLiveActivities?.(wireActivities());
}

function put(activity: LiveActivity): void {
  const existing = entries.find((one) => one.id === activity.id);
  //: 每次渲染都会再发布一次(useLiveActivity):没变就不惊动原生层。点击回调按 id 比不了,换了就照新的。
  const fields = ["state", "title", "detail", "progress", "icon", "priority"] as const;
  if (existing && fields.every((key) => existing[key] === activity[key])) return;
  const order = existing?.order ?? ++sequence;
  entries = [...entries.filter((one) => one.id !== activity.id), { ...activity, order }].sort(
    (a, b) => (b.priority ?? 0) - (a.priority ?? 0) || b.order - a.order,
  );
  sync();
}

function remove(id: string): void {
  const timer = timers.get(id);
  if (timer) clearTimeout(timer);
  timers.delete(id);
  if (!entries.some((one) => one.id === id)) return;
  entries = entries.filter((one) => one.id !== id);
  sync();
}

/**
 * 一件**还在做**的事:给了就挂上、变了就更新,给 null 或组件卸下就撤掉。发布它的组件就是它的主人。
 */
export function useLiveActivity(activity: LiveActivity | null): void {
  const id = activity?.id;
  React.useEffect(() => {
    if (activity) put(activity);
  });
  React.useEffect(() => {
    if (!id) return;
    return () => remove(id);
  }, [id]);
}

/**
 * 一件**刚结束**的事:亮 FLASH_MS 自己消失。同一个 id 再亮一次就重新计时。
 * 返回原生浮层是否接住了;false 时调用方仍应给出应用内提示。
 */
export function flashLiveActivity(activity: LiveActivity): boolean {
  const timer = timers.get(activity.id);
  if (timer) clearTimeout(timer);
  put(activity);
  timers.set(activity.id, setTimeout(() => remove(activity.id), FLASH_MS));
  return liveActivityAvailable();
}

/** 测试用:清空。 */
export function resetLiveActivities(): void {
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  entries = [];
  sequence = 0;
  sync();
}

// 原生浮层回传「用户点了哪一件」:按 id 找回发布时的回调。主进程已经把窗口叫到前面。
if (typeof window !== "undefined") {
  window.addEventListener("mosael:live-activity-open", (event) => {
    const id = (event as CustomEvent<unknown>).detail;
    if (typeof id !== "string") return;
    entries.find((one) => one.id === id)?.onOpen?.();
  });
}
