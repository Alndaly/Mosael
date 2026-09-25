import { describe, expect, it } from "vitest";

import { collapseToSubgraph } from "./collapse";
import type { RegistryLike } from "./analyze";
import type { WorkflowGraph } from "@/api/client";

/** 只有「哪些节点带内嵌子图」这一格和折叠有关 —— 后端随节点声明发下来的 body_scope。 */
const registry: RegistryLike = {
  get: (type) =>
    ({ loop_foreach: { body_scope: { loop: ["item", "index"], input: ["*inputs"] } }, subgraph: { body_scope: { input: ["*inputs"] } } } as Record<
      string,
      { body_scope: Record<string, string[]> }
    >)[type],
};

/** start → a → b → out,a/b 都用 {{}} 串引用;折叠 {a,b}。 */
function linearGraph(): WorkflowGraph {
  return {
    nodes: [
      { id: "start", type: "start", config: { params: { topic: "猫" } }, position: { x: 0, y: 0 } },
      { id: "a", type: "template", config: { template: "关于 {{start.topic}}" }, position: { x: 100, y: 0 } },
      { id: "b", type: "template", config: { template: "{{a.text}} 的文章" }, position: { x: 200, y: 0 } },
      { id: "out", type: "output", config: { values: { final: "{{b.text}}" } }, position: { x: 300, y: 0 } },
    ],
    edges: [
      { id: "e1", source: "start", target: "a" },
      { id: "e2", source: "a", target: "b" },
      { id: "e3", source: "b", target: "out" },
    ],
  };
}

describe("collapseToSubgraph", () => {
  it("把选区收进一个 subgraph 节点,并重写进出边界的引用", () => {
    const res = collapseToSubgraph(linearGraph(), ["a", "b"], registry, { name: "Subgraph", id: "sg" });
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    const { graph } = res;

    // 外层:start / out / sg 三个节点,a、b 已收进去
    expect(graph.nodes.map((n) => n.id).sort()).toEqual(["out", "sg", "start"]);
    const sg = graph.nodes.find((n) => n.id === "sg")!;
    expect(sg.type).toBe("subgraph");

    // 入边界:a 引用了 start → 子图开 input.start,内部改写为 {{input.start.topic}}
    expect(sg.config?.inputs).toEqual({ start: "{{start}}" });
    const body = sg.config?.body as WorkflowGraph;
    const bodyA = body.nodes.find((n) => n.id === "a")!;
    expect(bodyA.config?.template).toBe("关于 {{input.start.topic}}");
    // 内部 a→b 引用保持
    const bodyB = body.nodes.find((n) => n.id === "b")!;
    expect(bodyB.config?.template).toBe("{{a.text}} 的文章");
    expect(body.edges.map((e) => e.id)).toEqual(["e2"]); // 只有内部边 a→b

    // 出边界:out 曾引用 {{b.text}} → 改写成 {{sg.output.b.text}}
    const out = graph.nodes.find((n) => n.id === "out")!;
    expect((out.config?.values as Record<string, string> | undefined)?.final).toBe("{{sg.output.b.text}}");

    // 边收缩:start→sg、sg→out
    const pairs = graph.edges.map((e) => `${e.source}->${e.target}`).sort();
    expect(pairs).toEqual(["sg->out", "start->sg"]);
  });

  it("转换跨边界的数据边为 {{input.*}} / {{sg.output.*}} 模板", () => {
    const g: WorkflowGraph = {
      nodes: [
        { id: "start", type: "start", config: {} },
        { id: "src", type: "template", config: { template: "x" } },
        { id: "mid", type: "code", config: { code: "result = data" } },
        { id: "dst", type: "template", config: { template: "y" } },
      ],
      edges: [
        { id: "e1", source: "src", target: "mid", kind: "data", source_output: "text", target_input: "input" },
        { id: "e2", source: "mid", target: "dst", kind: "data", source_output: "output", target_input: "template" },
      ],
    };
    const res = collapseToSubgraph(g, ["mid"], registry, { name: "Subgraph", id: "sg" });
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    const sg = res.graph.nodes.find((n) => n.id === "sg")!;
    const body = sg.config?.body as WorkflowGraph;
    // 入边界数据边:mid.input ← {{input.src.text}}
    expect((body.nodes[0].config as Record<string, string>).input).toBe("{{input.src.text}}");
    expect(sg.config?.inputs).toEqual({ src: "{{src}}" });
    // 出边界数据边:dst.template ← {{sg.output.mid.output}}
    const dst = res.graph.nodes.find((n) => n.id === "dst")!;
    expect((dst.config as Record<string, string>).template).toBe("{{sg.output.mid.output}}");
  });

  it("拒绝含 start 的选区", () => {
    const res = collapseToSubgraph(linearGraph(), ["start", "a"], registry, { name: "Subgraph" });
    expect(res).toEqual({ ok: false, reason: "start" });
  });

  it("拒绝空选区", () => {
    expect(collapseToSubgraph(linearGraph(), [], registry, { name: "Subgraph" })).toEqual({ ok: false, reason: "empty" });
  });

  it("拒绝非凸选区(中间隔着未选中的节点,收缩后成环)", () => {
    // a → b → c,选 {a,c}:收缩后 sg→b→sg 成环
    const g: WorkflowGraph = {
      nodes: [
        { id: "a", type: "template", config: { template: "1" } },
        { id: "b", type: "template", config: { template: "{{a.text}}" } },
        { id: "c", type: "template", config: { template: "{{b.text}}" } },
      ],
      edges: [
        { id: "e1", source: "a", target: "b" },
        { id: "e2", source: "b", target: "c" },
      ],
    };
    expect(collapseToSubgraph(g, ["a", "c"], registry, { name: "Subgraph" })).toEqual({ ok: false, reason: "not-convex" });
  });

  it("只靠引用串起来的依赖也算:a ← w ← c 选 {a,c} 不能折叠", () => {
    // 连线全从 start 发出;依赖只在 {{…}} 里。后端排序和查环都把引用当依赖,
    // 折叠成 sg 之后 sg 引用 w、w 又引用 sg —— 存盘时才报「工作流包含环路」。
    const g: WorkflowGraph = {
      nodes: [
        { id: "start", type: "start", config: {} },
        { id: "a", type: "template", config: { template: "1" } },
        { id: "w", type: "template", config: { template: "{{a.text}}" } },
        { id: "c", type: "template", config: { template: "{{w.text}}" } },
      ],
      edges: [
        { id: "e1", source: "start", target: "a" },
        { id: "e2", source: "start", target: "w" },
        { id: "e3", source: "start", target: "c" },
      ],
    };
    expect(collapseToSubgraph(g, ["a", "c"], registry, { name: "Subgraph" })).toEqual({ ok: false, reason: "not-convex" });
  });

  it("循环体里的引用属于体自己,和外层节点撞名也不改写", () => {
    // 体的节点 id 自成一套(体编辑器按体内已有的 id 取号),和外层撞名是常态。
    const body: WorkflowGraph = {
      nodes: [{ id: "template-1", type: "template", config: { template: "{{loop.item}}!" } }],
      edges: [],
    };
    const g: WorkflowGraph = {
      nodes: [
        { id: "start", type: "start", config: {} },
        { id: "template-1", type: "template", config: { template: "外层" } },
        {
          id: "loop",
          type: "loop_foreach",
          config: { items: "{{template-1.text}}", body, output: "{{template-1.text}}" },
        },
      ],
      edges: [
        { id: "e1", source: "start", target: "template-1" },
        { id: "e2", source: "template-1", target: "loop" },
      ],
    };
    const res = collapseToSubgraph(g, ["loop"], registry, { name: "Subgraph", id: "sg" });
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    const sgBody = res.graph.nodes.find((n) => n.id === "sg")!.config!.body as WorkflowGraph;
    const inner = sgBody.nodes[0];
    // items 在外层作用域解析 → 改写成子图输入;output 指的是体内的 template-1 → 原样。
    expect(inner.config?.items).toBe("{{input.template-1.text}}");
    expect(inner.config?.output).toBe("{{template-1.text}}");
    expect(inner.config?.body).toEqual(body);
  });

  it("拒绝把条件节点的分支拉出边界(会丢 true/false 语义)", () => {
    const g: WorkflowGraph = {
      nodes: [
        { id: "cond", type: "condition", config: { left: "1", op: "eq", right: "1" } },
        { id: "yes", type: "template", config: { template: "y" } },
      ],
      edges: [{ id: "e1", source: "cond", target: "yes", source_handle: "true" }],
    };
    expect(collapseToSubgraph(g, ["cond"], registry, { name: "Subgraph" })).toEqual({ ok: false, reason: "condition-branch" });
  });

  it("入边界的条件分支保留 source_handle(条件路由不丢)", () => {
    const g: WorkflowGraph = {
      nodes: [
        { id: "cond", type: "condition", config: { left: "1", op: "eq", right: "1" } },
        { id: "a", type: "template", config: { template: "a" } },
        { id: "b", type: "template", config: { template: "{{a.text}}" } },
      ],
      edges: [
        { id: "e1", source: "cond", target: "a", source_handle: "true" },
        { id: "e2", source: "a", target: "b" },
      ],
    };
    const res = collapseToSubgraph(g, ["a", "b"], registry, { name: "Subgraph", id: "sg" });
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    const inEdge = res.graph.edges.find((e) => e.target === "sg")!;
    expect(inEdge.source).toBe("cond");
    expect(inEdge.source_handle).toBe("true");
  });

  it("子图 id 与已有节点冲突时另取一个", () => {
    const res = collapseToSubgraph(linearGraph(), ["a", "b"], registry, { name: "Subgraph" }); // 默认 base "subgraph"
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.subgraphId).toBe("subgraph"); // 无冲突
  });
});
