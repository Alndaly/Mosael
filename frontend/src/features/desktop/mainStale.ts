import React from "react";

/**
 * 开发时主进程过期了没有(主进程那边的判断见 electron/dev-staleness.cjs):主进程启动时加载的产物变了,而正在跑
 * 的还是旧的。界面上一条提示(MainStaleNotice)和调主进程的报错(页面工具的那句话)都读这一份。
 *
 * 一个模块级的小仓库,不放 context:提示挂在应用最外层,报错在内嵌浏览器的顶栏里,两边不在同一棵子树。
 * 正式打包的应用桥上没有 devMain,这里永远是「没过期」。
 */
export type MainStaleStatus = { files: string[]; canRestart: boolean };

const EMPTY: MainStaleStatus = { files: [], canRestart: false };
let status: MainStaleStatus = EMPTY;
let started = false;
const listeners = new Set<() => void>();

function set(next: MainStaleStatus): void {
  status = next;
  for (const listener of listeners) listener();
}

/** 第一次有人要看时接上桥:先问一次(界面刷新过的话主进程早就知道了),之后等它推。 */
function ensureStarted(): void {
  const bridge = typeof window === "undefined" ? undefined : window.mosaelDesktop?.devMain;
  if (started || !bridge) return;
  started = true;
  bridge.onStale((next) => set(next));
  void bridge.status().then(set, () => undefined);
}

export const mainStale = {
  get: (): MainStaleStatus => status,
  subscribe(listener: () => void): () => void {
    ensureStarted();
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** 测试用:回到没接过桥的样子。 */
  reset(): void {
    status = EMPTY;
    started = false;
  },
};

export function useMainStale(): MainStaleStatus {
  return React.useSyncExternalStore(mainStale.subscribe, mainStale.get, () => EMPTY);
}

/** 主进程过期了、而且能替用户重启。 */
export function staleMainRestartable(): boolean {
  return status.files.length > 0 && status.canRestart && Boolean(window.mosaelDesktop?.devMain);
}

/** 过期了且能重启就重启(交给主进程,dev-loop 会把 Electron 重新拉起来),返回重启了没有。 */
export function restartForStaleMain(): boolean {
  if (!staleMainRestartable()) return false;
  void window.mosaelDesktop?.devMain?.restart();
  return true;
}
