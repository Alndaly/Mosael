import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { neverRunReferences } from "@/features/workflows/analyze";
import {
  REFERENCE_HINT_EDGE_TYPE,
  isReferenceHintId,
  referenceHints,
  sameStructure,
  toReferenceHintEdges,
  type HintRegistry,
} from "@/features/workflows/referenceHints";

const TYPES: Record<string, ReturnType<HintRegistry["get"]>> = {
  start: { config: { params: { type: "object" } }, outputs: ["*params"] },
  llm: { config: { prompt: { type: "template" } }, outputs: ["text", "json"], label: "大模型" },
  template: { config: { template: { type: "template" } }, outputs: ["text"] },
  notify: { config: { title: { type: "template" }, body: { type: "template" } }, outputs: ["sent"] },
  condition: { config: { left: { type: "template" } }, outputs: ["result"] },
  code: { config: { code: { type: "code" }, input: { type: "object" } }, outputs: ["output"] },
  loop_foreach: {
    config: { items: { type: "template" }, inputs: { type: "object" }, body: { type: "graph" }, output: { type: "template" } },
    outputs: ["results"],
    body_scope: { loop: ["item", "index"], input: ["*inputs"] },
  },
};
const registry: HintRegistry = { get: (type) => TYPES[type] };
const top = { entryIsRoot: false };

function graph(nodes: WorkflowGraph["nodes"], edges: WorkflowGraph["edges"] = []): WorkflowGraph {
  return { nodes, edges };
}

const start = { id: "start", type: "start", config: { params: { topic: "猫" } } };
const plan = { id: "plan", type: "llm", config: { prompt: "写个分镜" } };

describe("引用 → 提示线", () => {
  it("从被引用节点的那个输出口出发;同一个口被引用几处只画一根,不同的口各一根", () => {
    const hints = referenceHints(
      graph(
        [
          start,
          plan,
          { id: "shot", type: "notify", config: { title: "{{plan.text}}", body: "{{plan.text}} / {{plan.json.shots}}" } },
        ],
        [
          { id: "e1", source: "start", target: "plan" },
          { id: "e2", source: "start", target: "shot" },
        ],
      ),
      registry,
      top,
    );
    expect(hints.map(({ source, sourceHandle, target, refs }) => ({ source, sourceHandle, target, refs }))).toEqual([
      { source: "plan", sourceHandle: "out:text", target: "shot", refs: ["{{plan.text}}"] },
      { source: "plan", sourceHandle: "out:json", target: "shot", refs: ["{{plan.json.shots}}"] },
    ]);
    expect(hints.every((hint) => isReferenceHintId(hint.id))).toBe(true);
    expect(new Set(hints.map((hint) => hint.id)).size).toBe(hints.length);
  });

  it("找不到具体口就从节点出发:开始节点的参数(通配)、条件节点(只画真假出口)、没声明的输出", () => {
    const hints = referenceHints(
      graph(
        [
          start,
          { id: "c", type: "condition", config: { left: "{{start.topic}}" } },
          plan,
          { id: "t", type: "template", config: { template: "{{start.topic}} {{c.result}} {{plan.nope}}" } },
        ],
        [
          { id: "e1", source: "start", target: "c" },
          { id: "e2", source: "c", target: "plan", source_handle: "true" },
          { id: "e3", source: "plan", target: "t" },
        ],
      ),
      registry,
      top,
    );
    expect(hints.map((hint) => [hint.source, hint.sourceHandle, hint.target])).toEqual([
      ["start", null, "t"],
      ["c", null, "t"],
      //: plan → t 已经有真连线,{{plan.nope}} 不再画。
    ]);
  });

  it("两头之间已有真连线(控制或数据)的不重复画;反方向的连线不算", () => {
    const hints = referenceHints(
      graph(
        [
          start,
          plan,
          { id: "a", type: "template", config: { template: "{{plan.text}}" } },
          { id: "b", type: "template", config: { template: "{{plan.json}}" } },
          { id: "c", type: "template", config: { template: "{{plan.text}}" } },
        ],
        [
          { id: "e1", source: "start", target: "plan" },
          { id: "e2", source: "plan", target: "a" },
          { id: "d1", source: "plan", target: "b", kind: "data", source_output: "text", target_input: "template" },
          { id: "e3", source: "c", target: "plan" },
        ],
      ),
      registry,
      top,
    );
    expect(hints.map((hint) => [hint.source, hint.target])).toEqual([["plan", "c"]]);
  });

  it("代码字段里的 {{…}} 不是引用;容器的 inputs / items 在这一层画,体内的 body / output 不在这一层画", () => {
    const hints = referenceHints(
      graph(
        [
          start,
          plan,
          { id: "run", type: "code", config: { code: "print('{{plan.text}}')", input: {} } },
          {
            id: "loop",
            type: "loop_foreach",
            config: {
              items: "{{plan.json.shots}}",
              inputs: { voice: "{{start.topic}}" },
              output: "{{plan.text}}",
              body: { nodes: [{ id: "plan", type: "template", config: { template: "{{loop.item}}" } }], edges: [] },
            },
          },
        ],
        [
          { id: "e1", source: "start", target: "plan" },
          { id: "e2", source: "start", target: "run" },
          { id: "e3", source: "start", target: "loop" },
        ],
      ),
      registry,
      top,
    );
    expect(hints.map((hint) => [hint.source, hint.sourceHandle, hint.target, hint.refs])).toEqual([
      ["plan", "out:json", "loop", ["{{plan.json.shots}}"]],
    ]);
  });

  it("循环体里的引用照画;体里没有入边的根是入口,被引用不算错误", () => {
    const body = graph(
      [
        { id: "style", type: "template", config: { template: "胶片感" } },
        { id: "shot", type: "template", config: { template: "{{loop.item}} {{style.text}}" } },
      ],
      [],
    );
    const hints = referenceHints(body, registry, { entryIsRoot: true });
    expect(hints.map((hint) => [hint.source, hint.sourceHandle, hint.target, hint.neverRuns])).toEqual([
      ["style", "out:text", "shot", false],
    ]);
    //: 同一张图放到顶层、shot 接上开始节点:没有开始节点连过来的 style 不会跑,同一根线就是错误色。
    const atTop = referenceHints(
      { nodes: [start, ...body.nodes], edges: [{ id: "e1", source: "start", target: "shot" }] },
      registry,
      top,
    );
    expect(atTop.map((hint) => [hint.source, hint.neverRuns])).toEqual([["style", true]]);
  });

  it("错误色和就绪检查 / 运行前检查是同一对:被引用的一定不会跑、引用方会跑;条件分支里的不算", () => {
    const g = graph(
      [
        start,
        { id: "props", type: "template", config: { template: "桌子" } },
        { id: "c", type: "condition", config: { left: "{{start.topic}}" } },
        { id: "voice", type: "template", config: { template: "画外音" } },
        { id: "set", type: "template", config: { template: "{{props.text}} {{voice.text}}" } },
        //: 自己也不会跑的引用方:两头都不跑,不算错。
        { id: "stray", type: "template", config: { template: "{{props.text}}" } },
      ],
      [
        { id: "e1", source: "start", target: "c" },
        { id: "e2", source: "c", target: "voice", source_handle: "true" },
        { id: "e3", source: "start", target: "set" },
      ],
    );
    const hints = referenceHints(g, registry, top);
    expect(hints.map((hint) => [hint.source, hint.target, hint.neverRuns])).toEqual([
      ["props", "set", true],
      ["voice", "set", false],
      ["props", "stray", false],
    ]);
    const blocked = neverRunReferences(g, registry, top).flatMap((one) => one.referencedBy.map((target) => [one.source, target]));
    expect(hints.filter((hint) => hint.neverRuns).map((hint) => [hint.source, hint.target])).toEqual(blocked);
  });
});

describe("提示线 → React Flow 的边", () => {
  const say = ((key: MessageKey) =>
    ({ wfRefHint: "引用 {refs}(只管先后,不会让「{source}」运行)", wfRefHintNeverRuns: "「{source}」不会跑:{refs}", listSeparator: "、" })[
      key as string
    ] ?? key) as (key: MessageKey) => string;

  const [ok, broken] = toReferenceHintEdges(
    [
      { id: "ref-hint:plan>out:text>shot", source: "plan", sourceHandle: "out:text", target: "shot", refs: ["{{plan.text}}", "{{plan.text.0}}"], neverRuns: false },
      { id: "ref-hint:props>>set", source: "props", sourceHandle: null, target: "set", refs: ["{{props.catalog}}"], neverRuns: true },
    ],
    { shape: "smoothstep", t: say, nodeName: (id) => ({ plan: "写分镜", props: "可用的 3D 道具" })[id] ?? id },
  );

  it("淡点线的样子只从 canvasEdges 那张表取;错误色是另一种", () => {
    expect(ok.className).toBe(canvasEdgeClass("ref", { hint: true }));
    expect(broken.className).toBe(canvasEdgeClass("ref-never-runs", { hint: true }));
    expect(ok.type).toBe(REFERENCE_HINT_EDGE_TYPE);
    expect(ok.data?.shape).toBe("smoothstep");
  });

  it("不能选中、删除、拖去重连,不进 Tab 序;不画箭头(盖掉默认箭头)", () => {
    for (const edge of [ok, broken]) {
      expect(edge).toMatchObject({ selectable: false, deletable: false, focusable: false, reconnectable: false });
      expect("markerEnd" in edge && edge.markerEnd === undefined).toBe(true);
    }
  });

  it("悬停的说明:引用的写法、被引用节点的名字;找不到具体口时从节点出发", () => {
    expect(ok.data?.title).toBe("引用 {{plan.text}}、{{plan.text.0}}(只管先后,不会让「写分镜」运行)");
    expect(ok.ariaLabel).toBe(ok.data?.title);
    expect(broken.data?.title).toBe("「可用的 3D 道具」不会跑:{{props.catalog}}");
    expect(ok.sourceHandle).toBe("out:text");
    expect(broken.sourceHandle).toBeUndefined();
  });
});

describe("只在图的结构变了时重算", () => {
  const g = graph([start, { ...plan, position: { x: 0, y: 0 } }], [{ id: "e1", source: "start", target: "plan" }]);

  it("拖动只换位置:结构没变", () => {
    const dragged = { ...g, nodes: g.nodes.map((node) => (node.id === "plan" ? { ...node, position: { x: 40, y: 8 } } : node)) };
    expect(sameStructure(g, dragged)).toBe(true);
  });

  it("改了配置、名字、连线、增删节点:结构变了", () => {
    const withConfig = { ...g, nodes: g.nodes.map((node) => (node.id === "plan" ? { ...node, config: { prompt: "{{start.topic}}" } } : node)) };
    const renamed = { ...g, nodes: g.nodes.map((node) => (node.id === "plan" ? { ...node, name: "写分镜" } : node)) };
    expect(sameStructure(g, withConfig)).toBe(false);
    expect(sameStructure(g, renamed)).toBe(false);
    expect(sameStructure(g, { ...g, edges: [] })).toBe(false);
    expect(sameStructure(g, { ...g, nodes: g.nodes.slice(1) })).toBe(false);
  });
});
