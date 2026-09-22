/**
 * 功能模块之间**不得互相依赖**。
 *
 * 一处功能引用另一处很常见也没问题(画板要放一张 3D 场景卡、剪辑页要嵌智能体),那是组合。
 * 但**两边互相引用**永远说明有个东西站错了地方:通常是一个通用工具住在了某个功能里,
 * 于是别人只能反过来去拿它。排查那一轮找到六对,每一对都是这个成因 ——
 *
 *   notes ↔ agent          Markdown 渲染、代码高亮、输入框小条的类型
 *   boards ↔ scenes        useAutosave
 *   editor ↔ voice         useSamplePlayer
 *   settings ↔ voice       pollWhileUnsettled
 *   boards ↔ collaboration 评论正文的渲染
 *   editor ↔ media         录制
 *
 * 循环本身不会报错、也不会崩,只是让"谁依赖谁"再也说不清:改一个 hook 要同时想三个页面,
 * 而新来的人从任何一端读进去都会绕回原地。通用的东西放 `lib/` 或 `components/`,
 * 属于某个领域的东西放它自己的领域里(评论归协作、录制归素材)。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const FEATURES = join(import.meta.dirname);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

/** 每个功能模块引用了哪些别的功能模块。`import type` 也算:它同样表达"我认识你"。 */
function dependencies(): Map<string, Set<string>> {
  const edges = new Map<string, Set<string>>();
  for (const feature of readdirSync(FEATURES).filter((one) => statSync(join(FEATURES, one)).isDirectory())) {
    const found = new Set<string>();
    for (const file of sources(join(FEATURES, feature))) {
      for (const match of readFileSync(file, "utf8").matchAll(/from "@\/features\/([\w-]+)\//g)) {
        if (match[1] !== feature) found.add(match[1]);
      }
    }
    edges.set(feature, found);
  }
  return edges;
}

/**
 * 依赖图里所有的环,不只是 A ↔ B。
 *
 * **判据此前只认二元环**(`edges.get(other)?.has(feature)`)—— 而 A → B → C → A 在
 * "谁依赖谁说不清了"这件事上和二元环一模一样:从任何一端读进去都会绕回原地,改一个 hook
 * 仍然要同时想三个页面。二元只是**当时找到的那六对**碰巧长的样子,不是这条规矩的边界。
 *
 * 用 Tarjan 找强连通分量:一个分量里多于一个结点,里面的每一对就都能互相到达。
 * 这同时把二元环覆盖了 —— 它是 n=2 的那种。
 */
function cycles(edges: Map<string, Set<string>>): string[] {
  let counter = 0;
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const found: string[] = [];

  const visit = (node: string): void => {
    index.set(node, counter);
    low.set(node, counter);
    counter += 1;
    stack.push(node);
    onStack.add(node);
    for (const next of edges.get(node) ?? []) {
      if (!edges.has(next)) continue; // 指向一个不存在的功能:那是别的问题
      if (!index.has(next)) {
        visit(next);
        low.set(node, Math.min(low.get(node)!, low.get(next)!));
      } else if (onStack.has(next)) {
        low.set(node, Math.min(low.get(node)!, index.get(next)!));
      }
    }
    if (low.get(node) !== index.get(node)) return;
    const component: string[] = [];
    for (;;) {
      const popped = stack.pop()!;
      onStack.delete(popped);
      component.push(popped);
      if (popped === node) break;
    }
    if (component.length > 1) found.push(component.sort().join(" ↔ "));
  };

  for (const node of edges.keys()) if (!index.has(node)) visit(node);
  return found.sort();
}

describe("功能模块的边界", () => {
  it("依赖图里没有环 —— 二元的,和更长的", () => {
    expect(
      cycles(dependencies()),
      "互相依赖的功能:把它们共用的那个东西挪到 lib/ 或 components/,或者归还给它真正的领域",
    ).toEqual([]);
  });

  it("三元环也拦得住 —— 二元只是当时找到的那六对碰巧长的样子", () => {
    const edges = new Map([
      ["a", new Set(["b"])],
      ["b", new Set(["c"])],
      ["c", new Set(["a"])],
      ["d", new Set(["a"])], // 单向依赖不算环
    ]);
    expect(cycles(edges)).toEqual(["a ↔ b ↔ c"]);
  });

  it("二元环照旧拦得住", () => {
    const edges = new Map([["a", new Set(["b"])], ["b", new Set(["a"])]]);
    expect(cycles(edges)).toEqual(["a ↔ b"]);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    const edges = dependencies();
    expect(edges.size).toBeGreaterThan(10);
    expect([...edges.values()].some((one) => one.size > 0), "一条功能间依赖都没扫到,八成是正则或目录写错了").toBe(true);
  });
});
