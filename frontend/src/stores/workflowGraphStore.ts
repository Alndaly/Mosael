import { createStore } from "zustand/vanilla";
import { temporal } from "zundo";

import type { WorkflowGraph } from "@/api/client";

/**
 * 工作流画布的可撤销状态层:graph 是唯一事实(节点/边/配置),用 zustand + zundo
 * 的 temporal 中间件记历史,给编辑器统一的 Cmd/Ctrl+Z 撤销 / 重做能力。
 *
 * 每个 WorkflowEditor 实例一个 store(按 workflow.id 重挂),历史不跨工作流串味。
 * 拖拽会连发 position 更新 → 用 handleSet 节流,让一次拖拽塌成一条历史,而不是每像素一条。
 */
export type GraphUpdater = WorkflowGraph | ((current: WorkflowGraph) => WorkflowGraph);

export interface GraphStore {
  graph: WorkflowGraph;
  setGraph: (updater: GraphUpdater) => void;
}

/** 极简 trailing 节流,免引依赖。 */
function throttleTrailing<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastArgs: A | null = null;
  return (...args: A) => {
    lastArgs = args;
    const now = Date.now();
    const remaining = ms - (now - last);
    if (remaining <= 0) {
      last = now;
      fn(...args);
    } else if (timer === null) {
      timer = setTimeout(() => {
        last = Date.now();
        timer = null;
        if (lastArgs) fn(...lastArgs);
      }, remaining);
    }
  };
}

export function createWorkflowGraphStore(initial: WorkflowGraph) {
  return createStore<GraphStore>()(
    temporal(
      (set) => ({
        graph: initial,
        setGraph: (updater) =>
          set((state) => ({
            graph: typeof updater === "function" ? updater(state.graph) : updater,
          })),
      }),
      {
        limit: 100,
        equality: (a, b) => a.graph === b.graph,
        handleSet: (handleSet) => throttleTrailing((state) => handleSet(state), 400),
      },
    ),
  );
}

export type WorkflowGraphStore = ReturnType<typeof createWorkflowGraphStore>;
