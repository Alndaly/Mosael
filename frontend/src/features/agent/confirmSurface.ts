import React from "react";

/**
 * 内联确认面(聊天流里的确认卡)登记处 —— 登记的是**哪些会话**正在自己处理确认卡。
 *
 * 确认卡按发起会话归属:有会话的卡在它自己那次对话里内联出现,没有会话的(MCP / 飞书等外部
 * 智能体)由右上角全局中心兜底。所以全局中心要排除的不是「有没有内联面」这个布尔,而是
 * **具体哪些会话已经有人管了** —— 否则一开聊天面板,外部智能体的卡就跟着被藏掉;而某次对话
 * 关掉之后,它遗留的待确认又没人显示,智能体会一直干等。
 *
 * 用模块级集合 + 订阅,避免为这点状态拉一个全局 store。
 */

const mounted = new Set<string>();
const listeners = new Set<() => void>();
// useSyncExternalStore 要求快照稳定:集合原地变更而引用不变会被判定为「没变」,所以每次变更
// 换一个新数组当快照。
let snapshot: readonly string[] = [];

function notify(): void {
  snapshot = [...mounted];
  for (const listener of listeners) listener();
}

/** 挂载登记;返回登出函数(直接用作 useEffect 的 cleanup)。 */
export function registerInlineConfirmSurface(sessionId: string): () => void {
  mounted.add(sessionId);
  notify();
  return () => {
    mounted.delete(sessionId);
    notify();
  };
}

/** 当前有内联面在管的会话 id。 */
export function useInlineConfirmSessions(): readonly string[] {
  return React.useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshot,
  );
}
