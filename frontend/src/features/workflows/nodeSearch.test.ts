import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { matchCanvasEntries } from "@/components/app/CanvasNodeSearch";
import { highlightAtLayer, nodeSearchEntryId, nodeSearchTargets } from "@/features/workflows/nodeSearch";

const registry = new Map<string, { label?: string; config?: Record<string, unknown> }>([
  ["loop", { label: "循环", config: { body: { type: "graph" } } }],
  ["llm", { label: "大模型", config: {} }],
]);

const node = (id: string, type: string, extra: Partial<WorkflowGraph["nodes"][number]> = {}) =>
  ({ id, type, position: { x: 0, y: 0 }, config: {}, ...extra }) as WorkflowGraph["nodes"][number];

//: 体里的 id 和主流程是两套命名空间:两层各有一个 `llm-1`。
const root: WorkflowGraph = {
  nodes: [
    node("llm-1", "llm"),
    node("loop-1", "loop", {
      name: "逐镜",
      config: { body: { nodes: [node("llm-1", "llm", { name: "合成口播" })], edges: [] } },
    }),
  ],
  edges: [],
};

describe("查找节点搜整张图", () => {
  it("列出每一层的节点;体里的在小字里说在哪一层;条目 id 按层区分", () => {
    const targets = nodeSearchTargets(root, registry, []);
    expect(targets.map((one) => [one.id, one.title, one.subtitle])).toEqual([
      [nodeSearchEntryId([], "llm-1"), "大模型", "大模型"],
      [nodeSearchEntryId([], "loop-1"), "逐镜", "循环"],
      [nodeSearchEntryId(["loop-1"], "llm-1"), "合成口播", "大模型 · 逐镜"],
    ]);
  });

  it("按节点 id 也搜得到", () => {
    const hits = matchCanvasEntries(nodeSearchTargets(root, registry, []), "loop-1");
    expect(hits.map((one) => one.nodeId)).toEqual(["loop-1"]);
  });

  it("当前这一层排最前", () => {
    const targets = nodeSearchTargets(root, registry, ["loop-1"]);
    expect(targets[0]).toMatchObject({ path: ["loop-1"], nodeId: "llm-1" });
  });

  it("画布上只圈当前这一层的命中,换回这一层的节点 id", () => {
    const targets = nodeSearchTargets(root, registry, []);
    const inner = nodeSearchEntryId(["loop-1"], "llm-1");
    const outer = nodeSearchEntryId([], "llm-1");
    const hit = { ids: new Set([inner, outer]), activeId: inner };
    expect(highlightAtLayer(hit, targets, [])).toEqual({ ids: new Set(["llm-1"]), activeId: null });
    expect(highlightAtLayer(hit, targets, ["loop-1"])).toEqual({ ids: new Set(["llm-1"]), activeId: "llm-1" });
    expect(highlightAtLayer(null, targets, [])).toBeNull();
  });
});
