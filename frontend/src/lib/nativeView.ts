import React from "react";

/**
 * 原生视图(内嵌浏览器、ComfyUI 工作台的画布)此刻在不在前台(ADR 0051)。
 *
 * 原生视图是挂在主窗口上的 `WebContentsView`,永远画在 Mosael 的界面上面,z-index 管不到它。它亮着的时候,应用级的浮层
 * (任务中心、命令面板、确认卡、提示条、免提浮标……)画在它底下就是看不见、点不着 —— 所以它们都要先问一句「原生视图在
 * 不在前台」,再决定画在哪(见 components/app/overNativeView)。内嵌浏览器和工作台是同一个视图机制,同一条规矩(D38)。
 *
 * 状态是主进程**推**的(`mosaelPublish.onViewState`);preload 记着最新一帧,订阅时先补发(见 electron/preload.cjs)。
 * 这里只订一次、全应用共用。网页版没有这座桥:永远「不在前台」。
 */
let inFront = false;
/** 订上了桥就是退订它的函数(只有测试会退订)。 */
let unsubscribe: (() => void) | null = null;
const listeners = new Set<() => void>();

function subscribeBridge(): void {
  if (unsubscribe || typeof window === "undefined") return;
  const bridge = window.mosaelPublish;
  if (typeof bridge?.onViewState !== "function") return;
  // 先占上:preload 订阅时当场补发最新的一帧,那一帧里有人回头来问,不能再订一次
  unsubscribe = () => undefined;
  unsubscribe = bridge.onViewState((state) => {
    const next = Boolean(state?.visible);
    if (next === inFront) return;
    inFront = next;
    for (const listener of listeners) listener();
  }) ?? (() => undefined);
}

/** 原生视图此刻在前台吗(内嵌浏览器、工作台)。 */
export function nativeViewInFront(): boolean {
  subscribeBridge();
  return inFront;
}

function subscribe(listener: () => void): () => void {
  subscribeBridge();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 同上,跟着变。 */
export function useNativeViewInFront(): boolean {
  return React.useSyncExternalStore(subscribe, nativeViewInFront, () => false);
}

/**
 * 要去别处之前先把前台的原生视图收起来(深链落地,D35)。内嵌浏览器和工作台都是「返回 Mosael」那一下:视图本身还活着,
 * 「在工作台里打开」回到同一张,没存的改动还在 —— 所以不另弹确认。不在前台就什么都不做。
 */
export async function leaveNativeView(): Promise<void> {
  if (!nativeViewInFront()) return;
  await window.mosaelPublish?.hideView().catch(() => undefined);
}

/** 测试用:退订上一座假桥,下一次问的时候订新的那座。 */
export function resetNativeViewForTests(): void {
  unsubscribe?.();
  unsubscribe = null;
  inFront = false;
  for (const listener of listeners) listener();
}
