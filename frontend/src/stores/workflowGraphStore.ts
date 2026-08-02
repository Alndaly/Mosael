import { createStore } from "zustand/vanilla";
import { temporal } from "zundo";

import type { WorkflowGraph } from "@/api/client";

/**
 * 工作流画布的可撤销状态层:graph 是唯一事实(节点/边/配置),用 zustand + zundo
 * 的 temporal 中间件记历史,给编辑器统一的 Cmd/Ctrl+Z 撤销 / 重做能力。
 *
 * 每个 WorkflowEditor 实例一个 store(按 workflow.id 重挂),历史不跨工作流串味。
 *
 * **拖拽会连发几十次 position 更新**,不合并的话一次拖拽就是几十条历史。合并的方式很讲究:
 *
 * - 曾经用的是 leading+trailing 节流,结果一次拖拽记**两条** —— 首次那条存的是拖之前的图
 *   (对的),尾随那条存的是拖到一半的图。于是按一次 Cmd+Z,节点只挪回几像素:看起来
 *   "什么都没发生,只是选中态变了",而那正是这个 bug 被报上来的样子。
 * - 现在是 leading-quiet:**一串操作里只记第一次**(也就是这串操作开始前的图),之后一直
 *   压住,直到安静满 COALESCE_MS 才重新武装。一次拖拽 = 一条历史 = 拖之前的位置。
 *
 * 只有显式声明 `coalesce` 的更新才合并(目前只有拖拽)。离散编辑(加节点、改配置、连线)
 * 一律立刻记 —— 两次连着点的操作各自可撤销,不该因为手快而被并成一条。
 */
export type GraphUpdater = WorkflowGraph | ((current: WorkflowGraph) => WorkflowGraph);

export interface SetGraphOptions {
  /** 连发型更新(拖拽):一串里只记一条历史,存的是这串开始前的图。 */
  coalesce?: boolean;
}

export interface GraphStore {
  graph: WorkflowGraph;
  setGraph: (updater: GraphUpdater, options?: SetGraphOptions) => void;
}

/** 一串连发里只记第一次,安静 ms 之后才重新武装。 */
function leadingQuiet<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return (...args: A) => {
    if (timer === null) fn(...args);
    else clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
    }, ms);
  };
}

/** 拖拽合并窗口:手停这么久就算这一串结束了。 */
export const COALESCE_MS = 400;

export function createWorkflowGraphStore(initial: WorkflowGraph) {
  // setGraph 与 handleSet 之间的一次性信号。zundo 的 handleSet 拿不到调用方的意图,而
  // "这次更新要不要合并"只有调用方知道 —— 一个同步的标志位是这里最直接的传递方式
  // (set 与 handleSet 在同一个同步调用栈里,不会交错)。
  let coalescing = false;

  return createStore<GraphStore>()(
    temporal(
      (set) => ({
        graph: initial,
        setGraph: (updater, options) => {
          coalescing = options?.coalesce === true;
          set((state) => ({
            graph: typeof updater === "function" ? updater(state.graph) : updater,
          }));
          coalescing = false;
        },
      }),
      {
        limit: 100,
        // 选中态、悬停这类不改图的更新,graph 引用不变 → 不进历史。
        // (zundo 在调 handleSet **之前**先跑这个,所以下面的合并逻辑根本看不到它们。)
        equality: (a, b) => a.graph === b.graph,
        handleSet: (handleSet) => {
          const coalesced = leadingQuiet((...args: Parameters<typeof handleSet>) => handleSet(...args), COALESCE_MS);
          return (...args: Parameters<typeof handleSet>) => {
            if (coalescing) coalesced(...args);
            else handleSet(...args);
          };
        },
      },
    ),
  );
}

export type WorkflowGraphStore = ReturnType<typeof createWorkflowGraphStore>;
