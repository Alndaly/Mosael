import React from "react";

/**
 * 内联确认面(聊天流里的确认卡)登记处。
 *
 * 同一张确认卡不该同时出现在聊天流和右上角全局中心两处:聊天面板打开时内联卡
 * 是主入口,全局 ConfirmationCenter 让位;没有任何聊天面板时(MCP / 飞书等外部
 * 智能体的请求)全局中心照常兜底。用模块级计数 + 订阅,避免为这一个布尔拉一个
 * 全局 store。
 */

let surfaces = 0;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** 挂载登记;返回登出函数(直接用作 useEffect 的 cleanup)。 */
export function registerInlineConfirmSurface(): () => void {
  surfaces += 1;
  notify();
  return () => {
    surfaces -= 1;
    notify();
  };
}

export function useInlineConfirmSurfaceOpen(): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => surfaces > 0,
  );
}
