/**
 * 棘轮:**运行时的 import 一个环都不许有** —— 文件之间、功能目录之间都一样。
 *
 * 环的代价不在打包器(ES 模块能处理),在读的人:两个文件互相认识,改一个就得懂另一个;而初始化顺序一旦
 * 依赖「谁先被加载」,常量在另一头读到的就是 `undefined`,只在某条加载路径上才出错。
 *
 * 清零的时候只有两处:`agent/SpeakButton ⇄ agent/messageUsage`(脚注按钮的样式常量住在了用它的那一头,
 * 挪进了 `agentRow`,和脚注行的外形放在一起)、`api/domains/feishu ⇄ api/client`(领域文件该像别的领域一样从
 * `api/transport` 取 `api`,不该回头认那层再导出)。功能目录之间本来就是单向的;这里守着不让它长出环。
 *
 * `import type` 和动态 `import("…")` 不算(见 importGraph):前者运行时不存在,后者是按需加载的边界。
 */
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { SRC, runtimeImports } from "@/design/importGraph";

export const RATCHET = true;

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (entry === "generated") continue;
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(relative(SRC, path));
  }
  return out;
}

/** Tarjan 强连通分量;长度 > 1 的就是环。 */
function cycles(graph: Map<string, string[]>): string[][] {
  let index = 0;
  const stack: string[] = [];
  const onStack = new Set<string>();
  const indexOf = new Map<string, number>();
  const low = new Map<string, number>();
  const found: string[][] = [];
  const visit = (v: string) => {
    indexOf.set(v, index);
    low.set(v, index);
    index += 1;
    stack.push(v);
    onStack.add(v);
    for (const w of graph.get(v) ?? []) {
      if (!indexOf.has(w)) {
        visit(w);
        low.set(v, Math.min(low.get(v)!, low.get(w)!));
      } else if (onStack.has(w)) low.set(v, Math.min(low.get(v)!, indexOf.get(w)!));
    }
    if (low.get(v) === indexOf.get(v)) {
      const component: string[] = [];
      let w: string;
      do {
        w = stack.pop()!;
        onStack.delete(w);
        component.push(w);
      } while (w !== v);
      if (component.length > 1) found.push(component.sort());
    }
  };
  for (const v of graph.keys()) if (!indexOf.has(v)) visit(v);
  return found;
}

const FILES = sources(SRC);
const FILE_GRAPH = new Map(FILES.map((file) => [file, runtimeImports(file).local]));

function featureOf(file: string): string | null {
  const parts = file.split("/");
  return parts[0] === "features" && parts.length > 2 ? parts[1] : null;
}

describe("import 不成环", () => {
  it("文件之间没有运行时的环", () => {
    expect(cycles(FILE_GRAPH).map((cycle) => cycle.join(" ⇄ "))).toEqual([]);
  });

  it("功能目录之间没有环(两个功能互相认识,就该把共用的那部分挪进 components / lib)", () => {
    const graph = new Map<string, string[]>();
    for (const [file, targets] of FILE_GRAPH) {
      const from = featureOf(file);
      if (!from) continue;
      const edges = graph.get(from) ?? [];
      for (const target of targets) {
        const to = featureOf(target);
        if (to && to !== from && !edges.includes(to)) edges.push(to);
      }
      graph.set(from, edges);
    }
    expect(cycles(graph).map((cycle) => cycle.join(" ⇄ "))).toEqual([]);
  });

  it("扫描面自己也有人看着", () => {
    expect(FILES.length).toBeGreaterThan(500);
    expect(FILE_GRAPH.get("features/agent/messageUsage.tsx")).toContain("features/agent/agentRow.ts");
    expect(cycles(new Map([["a", ["b"]], ["b", ["a"]], ["c", []]]))).toEqual([["a", "b"]]);
  });
});
