import { describe, expect, it } from "vitest";

import { isDataConnection, isDuplicateControlEdge, withDataInputBound } from "./connections";
import type { WorkflowGraph } from "@/api/client";

type WEdge = WorkflowGraph["edges"][number];

const control = (source: string, target: string, source_handle?: string): WEdge => ({
  id: `e-${source}-${target}`,
  source,
  target,
  source_handle: source_handle ?? null,
});
const data = (source: string, target: string): WEdge => ({
  id: `d-${source}-${target}`,
  source,
  target,
  kind: "data",
  source_output: "text",
  target_input: "prompt",
});

describe("isDataConnection", () => {
  it("out:x → in:y 才是数据边", () => {
    expect(isDataConnection("out:text", "in:prompt")).toBe(true);
    expect(isDataConnection(undefined, undefined)).toBe(false);
    expect(isDataConnection("out:text", undefined)).toBe(false); // 拖到默认接点 = 控制
    expect(isDataConnection("true", undefined)).toBe(false); // 条件分支 handle = 控制
  });
});

describe("isDuplicateControlEdge", () => {
  it("同 (source,target,handle) 的控制边算重复", () => {
    expect(isDuplicateControlEdge([control("a", "b")], "a", "b", undefined)).toBe(true);
  });
  it("条件分支不同 handle 不算重复", () => {
    expect(isDuplicateControlEdge([control("a", "b", "true")], "a", "b", "false")).toBe(false);
  });

  // 用户报的核心 bug:两种连线顺序不该有差异。
  it("已有数据边不该挡住同两节点间新建控制边(先连属性、再连顺序)", () => {
    expect(isDuplicateControlEdge([data("a", "b")], "a", "b", undefined)).toBe(false);
  });
  it("已有控制边也不影响再建数据边(数据边不走这个查重)", () => {
    // 数据边由 isDataConnection 判定后跳过控制边查重,这里仅确认反向:控制边在场时
    // 新控制边仍按同类比较(数据边不干扰)。
    expect(isDuplicateControlEdge([data("a", "b"), control("a", "c")], "a", "b", undefined)).toBe(false);
  });
});

describe("withDataInputBound", () => {
  const specs = { sequence_id: {}, track_id: { depends_on: "sequence_id" }, start: {} };
  const graph = {
    nodes: [
      { id: "tl", type: "timeline_create", config: {} },
      { id: "append", type: "timeline_append", config: { sequence_id: "seq-old", track_id: "trk-old", start: 3 } },
    ],
    edges: [],
  } as WorkflowGraph;

  it("嵌套属性端口写回对应配置叶子，而不是造一个带点号的顶层字段", () => {
    const nested = {
      nodes: [
        { id: "plan", type: "llm", config: {} },
        { id: "deliver", type: "output", config: { values: { note_id: "{{plan.text}}", report: "原值" } } },
      ],
      edges: [],
    } as WorkflowGraph;
    const next = withDataInputBound(
      nested,
      { targetId: "deliver", key: "values.note_id", sourceId: "plan", output: "text" },
      {},
    );

    expect(next.nodes[1].config).toEqual({ values: { note_id: "", report: "原值" } });
    expect(Object.keys(next.nodes[1].config ?? {})).not.toContain("values.note_id");
  });

  it("接上游:建数据边、进连接态、字面量清空,依赖它的轨道一并清掉(旧轨道不在新时间线上)", () => {
    const next = withDataInputBound(graph, { targetId: "append", key: "sequence_id", sourceId: "tl", output: "sequence_id" }, specs);
    const target = next.nodes.find((node) => node.id === "append")!;
    expect(target.inputs).toEqual(["sequence_id"]);
    expect(target.config).toEqual({ sequence_id: "", track_id: "", start: 3 });
    expect(next.edges).toEqual([
      { id: "d-tl-sequence_id-append-sequence_id", source: "tl", target: "append", kind: "data", source_output: "sequence_id", target_input: "sequence_id" },
    ]);
  });

  it("换接另一条:旧的那条数据边换掉,不留两条", () => {
    const once = withDataInputBound(graph, { targetId: "append", key: "sequence_id", sourceId: "tl", output: "sequence_id" }, specs);
    const twice = withDataInputBound(once, { targetId: "append", key: "sequence_id", sourceId: "tl", output: "other" }, specs);
    expect(twice.edges.map((edge) => edge.source_output)).toEqual(["other"]);
  });

  it("来源和输出都没变(下拉里重选同一项、画布上重拖同一条):原样返回,接好之后填的轨道不清", () => {
    //: 此前不比新旧,重选一次同一个来源,轨道就被清空 —— 而值从哪来根本没变。
    const once = withDataInputBound(graph, { targetId: "append", key: "sequence_id", sourceId: "tl", output: "sequence_id" }, specs);
    const filled = {
      ...once,
      nodes: once.nodes.map((node) => (node.id === "append" ? { ...node, config: { ...node.config, track_id: "trk-new" } } : node)),
    };
    const again = withDataInputBound(filled, { targetId: "append", key: "sequence_id", sourceId: "tl", output: "sequence_id" }, specs);
    expect(again).toBe(filled);
  });
});
