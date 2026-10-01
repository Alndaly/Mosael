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
    const targets = nodeSearchTargets(root, registry);
    expect(targets.map((one) => [one.id, one.title, one.subtitle])).toEqual([
      [nodeSearchEntryId([], "llm-1"), "大模型", "大模型"],
      [nodeSearchEntryId([], "loop-1"), "逐镜", "循环"],
      [nodeSearchEntryId(["loop-1"], "llm-1"), "合成口播", "大模型 · 逐镜"],
    ]);
  });

  it("按节点 id 也搜得到", () => {
    const hits = matchCanvasEntries(nodeSearchTargets(root, registry), "loop-1");
    expect(hits.map((one) => one.nodeId)).toEqual(["loop-1"]);
  });

  it("按图序排,和画布停在哪一层无关 —— 跳到别的层之后,Enter 的「下一个」还是同一串里的下一个", () => {
    //: 此前当前这一层排最前:按 Enter 跳进循环体,条目当场重排,游标指到了别的节点上。
    const ids = nodeSearchTargets(root, registry).map((one) => one.id);
    expect(ids).toEqual([
      nodeSearchEntryId([], "llm-1"),
      nodeSearchEntryId([], "loop-1"),
      nodeSearchEntryId(["loop-1"], "llm-1"),
    ]);
  });

  it("画布上圈当前这一层的命中,换回这一层的节点 id;更深处的命中圈在通往它的那个容器上", () => {
    const targets = nodeSearchTargets(root, registry);
    const inner = nodeSearchEntryId(["loop-1"], "llm-1");
    const outer = nodeSearchEntryId([], "llm-1");
    const hit = { ids: new Set([inner, outer]), activeId: inner };
    //: 站在主流程上:体里的「合成口播」看不见,圈落在装着它的「逐镜」上(同 issuesAtLayer 的折法)。
    expect(highlightAtLayer(hit, targets, [])).toEqual({ ids: new Set(["llm-1", "loop-1"]), activeId: null });
    expect(highlightAtLayer(hit, targets, ["loop-1"])).toEqual({ ids: new Set(["llm-1"]), activeId: "llm-1" });
    //: 只有体里命中时也一样;更外层、别的分支里的命中不在这一层画。
    expect(highlightAtLayer({ ids: new Set([inner]), activeId: null }, targets, [])).toEqual({
      ids: new Set(["loop-1"]),
      activeId: null,
    });
    expect(highlightAtLayer({ ids: new Set([outer]), activeId: outer }, targets, ["loop-1"])).toEqual({
      ids: new Set(),
      activeId: null,
    });
    expect(highlightAtLayer(null, targets, [])).toBeNull();
  });
});
