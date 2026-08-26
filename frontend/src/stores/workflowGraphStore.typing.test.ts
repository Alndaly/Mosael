/**
 * 打字是**连发**,不是离散编辑。
 *
 * 每敲一个字符记一条历史的话,Cmd+Z 一次只退回一个字母 —— 用户以为撤销坏了,其实是它
 * 太尽责。这和拖拽是同一个形状(一串连发应该塌成一条),所以用的是同一套合并机制。
 *
 * 这里钉的是:**一串输入撤销一次就回到打字之前**,而不是回到上一个字符。
 */
import { describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { COALESCE_MS, createWorkflowGraphStore } from "./workflowGraphStore";

function graphWith(text: string): WorkflowGraph {
  return {
    nodes: [{ id: "n1", type: "llm", name: "写提示词", config: { prompt: text }, position: { x: 0, y: 0 } }],
    edges: [],
  } as unknown as WorkflowGraph;
}

describe("打字合并成一条历史", () => {
  it("连打五个字符,撤销一次回到打字之前", () => {
    const store = createWorkflowGraphStore(graphWith(""));
    for (const text of ["你", "你好", "你好世", "你好世界", "你好世界!"]) {
      store.getState().setGraph(graphWith(text), { coalesce: true });
    }
    expect(store.getState().graph.nodes[0].config.prompt).toBe("你好世界!");

    store.temporal.getState().undo();
    expect(store.getState().graph.nodes[0].config.prompt).toBe("");
  });

  it("停顿之后是新的一串 —— 两次编辑各自可撤销", () => {
    vi.useFakeTimers();
    try {
      const store = createWorkflowGraphStore(graphWith(""));
      store.getState().setGraph(graphWith("第一段"), { coalesce: true });
      // 手停够久,这一串就算结束了
      vi.advanceTimersByTime(COALESCE_MS + 50);
      store.getState().setGraph(graphWith("第一段第二段"), { coalesce: true });

      store.temporal.getState().undo();
      expect(store.getState().graph.nodes[0].config.prompt).toBe("第一段");
      store.temporal.getState().undo();
      expect(store.getState().graph.nodes[0].config.prompt).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("离散编辑不合并 —— 两次连着点各自可撤销", () => {
    /** 换下拉、拨开关本来就是一步一个意图,手快不该把它们并成一条。 */
    const store = createWorkflowGraphStore(graphWith("原文"));
    store.getState().setGraph(graphWith("改法一"));
    store.getState().setGraph(graphWith("改法二"));

    store.temporal.getState().undo();
    expect(store.getState().graph.nodes[0].config.prompt).toBe("改法一");
    store.temporal.getState().undo();
    expect(store.getState().graph.nodes[0].config.prompt).toBe("原文");
  });
});
