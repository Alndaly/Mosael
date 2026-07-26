import { describe, expect, it } from "vitest";

import { isDataConnection, isDuplicateControlEdge } from "./connections";
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
