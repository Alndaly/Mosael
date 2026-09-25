import { describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { COALESCE_MS, createWorkflowGraphStore } from "@/stores/workflowGraphStore";

/**
 * 撤销历史的粒度。三条各自对着一个具体的坏结果:
 *
 * 选中进历史 → 按 Cmd+Z 什么都没变,用户以为撤销坏了;
 * 一次拖拽记两条 → 按一次只挪回几像素(**这就是那个 bug 被报上来的样子**);
 * 离散编辑被合并 → 连着加两个节点,一次撤销把两个都撤了。
 */
const at = (x: number): WorkflowGraph =>
  ({
    nodes: [{ id: "n1", type: "start", name: "s", position: { x, y: 0 }, config: {} }],
    edges: [],
  }) as unknown as WorkflowGraph;

const positions = (store: ReturnType<typeof createWorkflowGraphStore>) =>
  (store.temporal.getState().pastStates as Array<{ graph: WorkflowGraph }>).map(
    (past) => (past.graph.nodes[0] as unknown as { position: { x: number } }).position.x,
  );

describe("工作流撤销历史", () => {
  it("选中 / 悬停这类不改图的更新不进历史", () => {
    const store = createWorkflowGraphStore(at(0));
    // React Flow 的 select 变更走的也是 setGraph,只是 updater 原样返回 —— 引用不变就该被滤掉。
    store.getState().setGraph((current) => current);
    store.getState().setGraph((current) => current, { coalesce: "drag" });
    expect(store.temporal.getState().pastStates).toHaveLength(0);
  });

  it("一次拖拽只记一条,存的是**拖之前**的图", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(at(0));
      for (let x = 1; x <= 12; x += 1) {
        store.getState().setGraph(at(x), { coalesce: "drag" });
        vi.advanceTimersByTime(20);
      }
      vi.advanceTimersByTime(COALESCE_MS * 2);
      // 旧实现(leading+trailing 节流)在这里是 [0, 某个中间值] —— 撤一次只挪回几像素。
      expect(positions(store)).toEqual([0]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("两次拖拽之间手停过,就是两条", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(at(0));
      store.getState().setGraph(at(1), { coalesce: "drag" });
      vi.advanceTimersByTime(COALESCE_MS * 2);
      store.getState().setGraph(at(2), { coalesce: "drag" });
      vi.advanceTimersByTime(COALESCE_MS * 2);
      expect(positions(store)).toEqual([0, 1]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("离散编辑各记各的,哪怕手很快", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(at(0));
      store.getState().setGraph(at(1)); // 比如加一个节点
      vi.advanceTimersByTime(10);
      store.getState().setGraph(at(2)); // 紧接着又加一个
      vi.advanceTimersByTime(COALESCE_MS * 2);
      expect(positions(store)).toEqual([0, 1]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("不是同一串的连发不合并 —— 刚打完字紧接着改另一个字段,是两步", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(at(0));
      store.getState().setGraph(at(1), { coalesce: "n1.prompt" });
      vi.advanceTimersByTime(10);
      store.getState().setGraph(at(2), { coalesce: "n1.prompt" });
      vi.advanceTimersByTime(10);
      store.getState().setGraph(at(3), { coalesce: "n2.prompt" }); // 换了一个字段
      vi.advanceTimersByTime(COALESCE_MS * 2);
      expect(positions(store)).toEqual([0, 2]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("中间夹着一次离散编辑,这一串就断了", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(at(0));
      store.getState().setGraph(at(1), { coalesce: "n1.prompt" }); // 打字
      vi.advanceTimersByTime(10);
      store.getState().setGraph(at(2)); // 换了个下拉
      vi.advanceTimersByTime(10);
      store.getState().setGraph(at(3), { coalesce: "n1.prompt" }); // 回去接着打
      vi.advanceTimersByTime(COALESCE_MS * 2);
      expect(positions(store)).toEqual([0, 1, 2]);
    } finally {
      vi.useRealTimers();
    }
  });
});
