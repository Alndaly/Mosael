import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { RegistryLike } from "@/features/workflows/analyze";
import { pasteNodes } from "@/features/workflows/clipboard";

/** 只有「哪些节点带内嵌子图」和粘贴有关 —— 后端随节点声明发下来的 body_scope。 */
const registry: RegistryLike = {
  get: (type) =>
    ({
      loop_foreach: { body_scope: { loop: ["item", "index"], input: ["*inputs"] } },
      subgraph: { body_scope: { input: ["*inputs"] } },
      code: { config: { code: { type: "code" }, input: { type: "object" } } },
    } as Record<string, { body_scope?: Record<string, string[]>; config?: Record<string, unknown> }>)[type],
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

  it("代码字段里的 {{…}} 不是引用,原样粘过去;入参里的照常换", () => {
    //: 代码不插值(后端 code_fields):那一段是代码里的字面文字。改写它等于悄悄改了用户的代码。
    const graph = { nodes: [node("llm-1", "llm")], edges: [] } as WorkflowGraph;
    const clip = {
      nodes: [
        node("llm-1", "llm"),
        node("code-1", "code", { code: "print('{{llm-1.text}}')", input: { t: "{{llm-1.text}}" } }),
      ],
      edges: [],
    };
    const copy = pasteNodes(graph, clip, registry)!.graph.nodes.find((one) => one.id === "code-1")!;
    expect(copy.config).toEqual({ code: "print('{{llm-1.text}}')", input: { t: "{{llm-2.text}}" } });
  });

  it("给了落点(鼠标处):整组左上角对齐到那,节点间相对位置原样保留;没给就按老习惯右下错开", () => {
    const graph = { nodes: [node("start", "start")], edges: [] } as WorkflowGraph;
    const clip = {
      nodes: [
        { ...node("a", "llm"), position: { x: 300, y: 200 } },
        { ...node("b", "llm"), position: { x: 420, y: 260 } },
      ],
      edges: [],
    };
    // 落点 {x:1000,y:500}:组左上角(min 300,200)对齐到 (1000,500),两个节点各平移 (+700,+300)。
    const pasted = pasteNodes(graph, clip, registry, { x: 1000, y: 500 })!;
    const byId = new Map(pasted.graph.nodes.map((one) => [one.id, one]));
    expect(byId.get("llm-1")!.position).toEqual({ x: 1000, y: 500 });
    expect(byId.get("llm-2")!.position).toEqual({ x: 1120, y: 560 }); // 相对间距 (120,60) 原样保留

    // 没给落点:退回原「右下错开 PASTE_OFFSET」。
    const fallback = pasteNodes(graph, clip, registry)!;
    const fb = new Map(fallback.graph.nodes.map((one) => [one.id, one]));
    expect(fb.get("llm-1")!.position).toEqual({ x: 300 + 48, y: 200 + 48 });
  });

  it("带连线粘贴:对外连线重接到仍在图里的那端;普通粘贴不接", () => {
    const dataEdge = { id: "d-llm-1-json-llm-2-prompt", source: "llm-1", target: "llm-2", kind: "data", source_output: "json", target_input: "prompt" } as const;
    const graph = {
      nodes: [node("start", "start"), node("llm-1", "llm"), node("llm-2", "llm")],
      edges: [{ ...dataEdge }],
    } as unknown as WorkflowGraph;
    // 只复制 llm-2;它对外的数据边(来自 llm-1)记进 external。
    const clip = { nodes: [node("llm-2", "llm")], edges: [], external: [{ ...dataEdge }] };
    // 带连线粘贴(Cmd+Shift+V):新节点(llm-3)接上 llm-1 的 json。
    const withConn = pasteNodes(graph, clip as never, registry, null, true)!;
    expect(withConn.graph.edges).toContainEqual(
      expect.objectContaining({ id: "d-llm-1-json-llm-3-prompt", source: "llm-1", target: "llm-3", kind: "data" }),
    );
    // 普通粘贴(Cmd+V):不带外部连线,边数不变。
    const plain = pasteNodes(graph, clip as never, registry, null, false)!;
    expect(plain.graph.edges).toHaveLength(graph.edges.length);
  });
});
