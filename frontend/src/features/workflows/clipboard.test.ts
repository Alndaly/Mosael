import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { RegistryLike } from "@/features/workflows/analyze";
import { pasteNodes } from "@/features/workflows/clipboard";

/** 只有「哪些节点带内嵌子图」和粘贴有关 —— 后端随节点声明发下来的 body_scope。 */
const registry: RegistryLike = {
  get: (type) =>
    ({ loop_foreach: { body_scope: ["loop", "input"] }, subgraph: { body_scope: ["input"] } } as Record<
      string,
      { body_scope: string[] }
    >)[type],
};

const node = (id: string, type: string, config: Record<string, unknown> = {}) =>
  ({ id, type, position: { x: 0, y: 0 }, config }) as WorkflowGraph["nodes"][number];

describe("粘贴一组节点", () => {
  it("组内引用换成新 id,组外引用和原图不动", () => {
    const graph = { nodes: [node("start", "start"), node("llm-1", "llm"), node("template-1", "template")], edges: [] } as WorkflowGraph;
    const clip = {
      nodes: [node("llm-1", "llm"), node("template-1", "template", { template: "{{ llm-1.text }} {{start.x}}", list: ["{{llm-1.json}}"] })],
      edges: [{ id: "e-llm-1-template-1", source: "llm-1", target: "template-1" }],
    };
    const pasted = pasteNodes(graph, clip, registry)!;
    expect(pasted.pastedIds).toEqual(["llm-2", "template-2"]);
    const copy = pasted.graph.nodes.find((one) => one.id === "template-2")!;
    expect(copy.config).toEqual({ template: "{{llm-2.text}} {{start.x}}", list: ["{{llm-2.json}}"] });
    expect(pasted.graph.edges.at(-1)).toMatchObject({ id: "e-llm-2-template-2", source: "llm-2", target: "template-2" });
    expect(clip.nodes[1].config).toEqual({ template: "{{ llm-1.text }} {{start.x}}", list: ["{{llm-1.json}}"] });
  });

  it("循环体里的引用是体内的命名空间,不拿外层的换名表去改", () => {
    const body = { nodes: [node("llm-1", "llm", { prompt: "{{loop.item}}" })], edges: [] };
    const graph = { nodes: [node("llm-1", "llm")], edges: [] } as WorkflowGraph;
    const clip = {
      nodes: [node("llm-1", "llm"), node("loop-1", "loop_foreach", { items: "{{llm-1.json}}", body, output: "{{llm-1.text}}" })],
      edges: [],
    };
    const loop = pasteNodes(graph, clip, registry)!.graph.nodes.find((one) => one.type === "loop_foreach")!;
    expect(loop.config).toEqual({ items: "{{llm-2.json}}", body, output: "{{llm-1.text}}" });
  });

  it("start 不复制;只剩 start 时什么都不粘", () => {
    const graph = { nodes: [node("start", "start")], edges: [] } as WorkflowGraph;
    expect(pasteNodes(graph, { nodes: [node("start", "start")], edges: [] }, registry)).toBeNull();
  });
});
