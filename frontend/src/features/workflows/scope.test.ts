import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { bodyKey, graphAtScope, parseScopeId, scopeId, scopeIds, withGraphAtScope } from "@/features/workflows/scope";

//: 容器由声明认出来:有一个 graph 字段就是容器。类型名故意是假的。
const registry = new Map<string, { config: Record<string, unknown> }>([
  ["box", { config: { inner: { type: "graph" }, note: { type: "template" } } }],
  ["leaf", { config: { text: { type: "template" } } }],
]);

const node = (id: string, type: string, config: Record<string, unknown> = {}) =>
  ({ id, type, position: { x: 0, y: 0 }, config }) as WorkflowGraph["nodes"][number];

const deepest = { nodes: [node("leaf-1", "leaf")], edges: [] };
const root: WorkflowGraph = {
  nodes: [node("box-1", "box", { inner: { nodes: [node("box-2", "box", { inner: deepest })], edges: [] } }), node("leaf-1", "leaf")],
  edges: [],
};

describe("画布的层", () => {
  it("容器按声明认:有 graph 字段的才是", () => {
    expect(bodyKey(registry, "box")).toBe("inner");
    expect(bodyKey(registry, "leaf")).toBeNull();
    expect(bodyKey(registry, "unknown")).toBeNull();
  });

  it("按路径读到那一层;路径断了是 null;还没建的体是空图", () => {
    expect(graphAtScope(root, [], registry)).toBe(root);
    expect(graphAtScope(root, ["box-1", "box-2"], registry)).toBe(deepest);
    expect(graphAtScope(root, ["leaf-1"], registry)).toBeNull();
    expect(graphAtScope(root, ["gone"], registry)).toBeNull();
    const fresh = { nodes: [node("box-9", "box", { inner: "" })], edges: [] } as WorkflowGraph;
    expect(graphAtScope(fresh, ["box-9"], registry)).toEqual({ nodes: [], edges: [] });
  });

  it("写回只换路径上那一串,别的节点原样(同一个对象)", () => {
    const next = { nodes: [], edges: [] };
    const written = withGraphAtScope(root, ["box-1", "box-2"], next, registry);
    expect(graphAtScope(written, ["box-1", "box-2"], registry)).toBe(next);
    expect(written.nodes[1]).toBe(root.nodes[1]);
    expect(graphAtScope(root, ["box-1", "box-2"], registry)).toBe(deepest);
  });

  it("列出所有能进去的层,路径可以存下来再读回", () => {
    expect(scopeIds(root, registry)).toEqual([scopeId(["box-1"]), scopeId(["box-1", "box-2"])]);
    expect(parseScopeId(scopeId(["box-1", "box-2"]))).toEqual(["box-1", "box-2"]);
    expect(parseScopeId("loop-1")).toEqual([]);
    expect(parseScopeId(null)).toEqual([]);
  });
});
