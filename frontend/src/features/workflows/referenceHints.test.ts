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
  output: { config: { values: { type: "object" } }, outputs: ["*values"] },
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
  it("每条引用落到使用它的属性端口，具名输出的属性不再共用流程入口", () => {
    const hints = referenceHints(
      graph([
        plan,
        {
          id: "deliver",
          type: "output",
          config: {
            values: {
              note_id: "{{plan.text}}",
              report: "{{plan.json.report}}",
            },
          },
        },
      ]),
      registry,
      top,
    );

    expect(hints.map(({ sourceHandle, targetHandle, refs }) => ({ sourceHandle, targetHandle, refs }))).toEqual([
      { sourceHandle: "out:text", targetHandle: "in:values.note_id", refs: ["{{plan.text}}"] },
      { sourceHandle: "out:json", targetHandle: "in:values.report", refs: ["{{plan.json.report}}"] },
    ]);
  });

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
    expect(hints.map(({ source, sourceHandle, target, targetHandle, refs }) => ({ source, sourceHandle, target, targetHandle, refs }))).toEqual([
      { source: "plan", sourceHandle: "out:text", target: "shot", targetHandle: "in:title", refs: ["{{plan.text}}"] },
      { source: "plan", sourceHandle: "out:text", target: "shot", targetHandle: "in:body", refs: ["{{plan.text}}"] },
      { source: "plan", sourceHandle: "out:json", target: "shot", targetHandle: "in:body", refs: ["{{plan.json.shots}}"] },
    ]);
    expect(hints.every((hint) => isReferenceHintId(hint.id))).toBe(true);
    expect(new Set(hints.map((hint) => hint.id)).size).toBe(hints.length);
  });

  it("找不到具体口就从节点出发:条件节点(出口是真假两路)、没声明的输出、开始节点没有的参数", () => {
    const hints = referenceHints(
      graph(
        [
          start,
          { id: "c", type: "condition", config: { left: "{{start.nope}}" } },
          plan,
          { id: "t", type: "template", config: { template: "{{start.nope}} {{c.result}} {{plan.nope}}" } },
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
      ["start", null, "c"],
      ["start", null, "t"],
      ["c", null, "t"],
      //: plan → t 已经有控制线,{{plan.nope}} 不再画。start 的控制线只表达执行顺序，属性依赖仍然可见。
    ]);
  });

  it("开始节点的参数各有一个口:引用从那个参数的口出发;接进流程的控制边另走顶上的控制出口,所以照画", () => {
    //: 控制边只说先后,而开始节点永远最先跑 —— 它说不出「哪个参数流到哪」。参数线才说得出,哪怕两头已有那条控制边。
    const hints = referenceHints(
      graph(
        [
          { id: "start", type: "start", config: { params: { topic: "猫", style: "", tone: "" } } },
          { id: "plan", type: "llm", inputs: ["prompt"], config: { prompt: "", system: "" } },
          { id: "t", type: "template", config: { template: "{{start.topic}} / {{start.style}} / {{start.tone}}" } },
        ],
        [
          { id: "e1", source: "start", target: "plan" },
          { id: "e2", source: "plan", target: "t" },
          //: 已经从 style 口拉了一条数据边进 plan:同一个口到同一个节点不再叠一根提示线。
          { id: "d1", source: "start", target: "plan", kind: "data", source_output: "style", target_input: "prompt" },
        ],
      ),
      { get: (type) => (type === "llm" ? { ...TYPES.llm!, config: { prompt: { type: "template" }, system: { type: "template" } } } : TYPES[type]) },
      top,
    );
    expect(hints.map((hint) => [hint.source, hint.sourceHandle, hint.target])).toEqual([
      ["start", "out:topic", "t"],
      ["start", "out:style", "t"],
      ["start", "out:tone", "t"],
    ]);
    const plan = referenceHints(
      graph(
        [
          { id: "start", type: "start", config: { params: { topic: "猫", style: "" } } },
          { id: "plan", type: "llm", inputs: ["prompt"], config: { prompt: "", system: "{{start.style}} {{start.topic}}" } },
        ],
        [
          { id: "e1", source: "start", target: "plan" },
          { id: "d1", source: "start", target: "plan", kind: "data", source_output: "style", target_input: "prompt" },
        ],
      ),
      { get: (type) => (type === "llm" ? { ...TYPES.llm!, config: { prompt: { type: "template" }, system: { type: "template" } } } : TYPES[type]) },
      top,
    );
    expect(plan.map((hint) => [hint.source, hint.sourceHandle, hint.target])).toEqual([
      ["start", "out:style", "plan"],
      ["start", "out:topic", "plan"],
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
          { id: "d1", source: "plan", target: "b", kind: "data", source_output: "json", target_input: "template" },
          { id: "e3", source: "c", target: "plan" },
        ],
      ),
      registry,
      top,
    );
    expect(hints.map((hint) => [hint.source, hint.target])).toEqual([["plan", "c"]]);
  });

  it("同一对节点接好一个属性，只隐藏那一项，其他属性提示线仍保留", () => {
    const hints = referenceHints(
      graph(
        [
          plan,
          { id: "deliver", type: "output", config: { values: { note: "{{plan.text}}", report: "{{plan.json}}" } } },
        ],
        [
          {
            id: "d1",
            source: "plan",
            target: "deliver",
            kind: "data",
            source_output: "text",
            target_input: "values.note",
          },
        ],
      ),
      registry,
      top,
    );

    expect(hints.map(({ sourceHandle, targetHandle }) => [sourceHandle, targetHandle])).toEqual([
      ["out:json", "in:values.report"],
    ]);
  });

  it("落在表单能单独填的那一格:生成参数的一项、输入素材的一行各一个口;原始 JSON 框里几处引用是那一格一个口", () => {
    const shaped: HintRegistry = {
      get: (type) =>
        type === "gen"
          ? {
              config: {
                parameters: { type: "object", entry_labels: "generation_parameters" },
                source_assets: { type: "template", lines: true, entry_labels: "source_roles" },
              },
              outputs: ["asset_id"],
            }
          : type === "plan"
            ? { config: { json_schema: { type: "object", editor: "json" } }, outputs: ["json"] }
            : TYPES[type],
    };
    const hints = referenceHints(
      graph([
        start,
        { id: "g", type: "gen", config: { parameters: { aspect_ratio: "{{start.ratio}}" }, source_assets: ["{{start.photo}}:first_frame"] } },
        {
          id: "p",
          type: "plan",
          config: { json_schema: { properties: { a: { description: "{{start.secs}} 秒" }, b: { description: "{{start.secs}} 秒内" } } } },
        },
      ]),
      shaped,
      top,
    );
    expect(hints.map((hint) => [hint.target, hint.targetHandle, hint.refs])).toEqual([
      ["g", "in:parameters.aspect_ratio", ["{{start.ratio}}"]],
      ["g", "in:source_assets.0", ["{{start.photo}}"]],
      //: 此前是三个都叫 `description` 的口(这里是两个),各连一根线。
      ["p", "in:json_schema", ["{{start.secs}}"]],
    ]);
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
      ["start", "out:topic", "loop", ["{{start.topic}}"]],
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
      ["start", "c", false],
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
    //: 引用说成名字(没给目录时按路径分段),不摆 `{{…}}`;编辑器里给的是按图起名的目录(见 refsShownAsNames)。
    expect(ok.data?.title).toBe("引用 plan · text、plan · text · 0(只管先后,不会让「写分镜」运行)");
    expect(ok.ariaLabel).toBe(ok.data?.title);
    expect(broken.data?.title).toBe("「可用的 3D 道具」不会跑:props · catalog");
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
