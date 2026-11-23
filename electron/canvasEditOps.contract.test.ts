/**
 * 画布编辑指令的主进程与桥两侧:跑 contracts/canvas-edit-ops.json(插件那一侧见 backend/tests/test_canvas_edit_contract.py)。
 *
 * - 主进程(ipc-contract 的 parseEditOps):每种指令的示例原样通过、字段表与语料一致、语料里该拒的都拒、上限一致;
 * - 桥(browser/comfy/comfyWorkbench.ts 的页面脚本):每种指令都有一处照做的分支,没有语料外的指令。
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const contract = require("./ipc-contract.cjs");
const corpus = JSON.parse(readFileSync(new URL("../contracts/canvas-edit-ops.json", import.meta.url), "utf8")) as {
  limits: { ops_per_batch: number; value_chars: number; coordinate: number };
  ops: Record<string, { fields: string[]; example: Record<string, unknown> }>;
  rejected: { why: string; op: Record<string, unknown> }[];
};

const EXPECT = { key: "workflows/a.json", revision: 0 };
const apply = (ops: unknown[]) =>
  contract.parseComfyWorkbenchCall({ connectionId: "c1", call: { op: "applyOps", ops, expect: EXPECT } }).call.ops;

/** 语料里写 `@value_chars+1` 的值是「刚好超上限一个字」。 */
function expand(op: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(op).map(([key, value]) => [key, value === "@value_chars+1" ? "x".repeat(corpus.limits.value_chars + 1) : value]),
  );
}

describe("主进程:ipc-contract 的 parseEditOps", () => {
  it("每种指令的示例原样通过,字段都是这种指令认的", () => {
    for (const [kind, { fields, example }] of Object.entries(corpus.ops)) {
      expect(apply([example]), kind).toEqual([example]);
      expect(Object.keys(example).every((key) => fields.includes(key)), kind).toBe(true);
    }
  });

  it("字段表与语料一致:任一种指令多带一个语料外的字段都拒", () => {
    for (const [kind, { example }] of Object.entries(corpus.ops)) {
      expect(() => apply([{ ...example, extra: 1 }]), kind).toThrow(/unexpected/);
    }
  });

  it("语料里该拒的都拒", () => {
    for (const { why, op } of corpus.rejected) expect(() => apply([expand(op)]), why).toThrow();
  });

  it("上限与语料一致", () => {
    const one = corpus.ops.remove_node.example;
    expect(apply(Array.from({ length: corpus.limits.ops_per_batch }, () => one))).toHaveLength(corpus.limits.ops_per_batch);
    expect(() => apply(Array.from({ length: corpus.limits.ops_per_batch + 1 }, () => one))).toThrow(/at most/);
    const longest = { ...corpus.ops.set_widget.example, value: "x".repeat(corpus.limits.value_chars) };
    expect(apply([longest])).toEqual([longest]);
    const farthest = { ...corpus.ops.set_position.example, x: corpus.limits.coordinate };
    expect(apply([farthest])).toEqual([farthest]);
  });
});

describe("桥:comfyWorkbench.ts 的页面脚本", () => {
  const source = readFileSync(new URL("./browser/comfy/comfyWorkbench.ts", import.meta.url), "utf8");
  const handled = new Set([...source.matchAll(/op\.op === "([a-z_]+)"/g)].map((match) => match[1]));

  it("每种指令都有照做的分支,也没有语料外的", () => {
    expect([...handled].sort()).toEqual(Object.keys(corpus.ops).sort());
  });
});
