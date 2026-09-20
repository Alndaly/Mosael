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

describe("功能模块的边界", () => {
  it("没有两个功能互相依赖", () => {
    const edges = dependencies();
    const cycles: string[] = [];
    for (const [feature, others] of edges) {
      for (const other of others) {
        if (edges.get(other)?.has(feature) && feature < other) cycles.push(`${feature} ↔ ${other}`);
      }
    }
    expect(cycles, "互相依赖的功能:把它们共用的那个东西挪到 lib/ 或 components/,或者归还给它真正的领域").toEqual([]);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    const edges = dependencies();
    expect(edges.size).toBeGreaterThan(10);
    expect([...edges.values()].some((one) => one.size > 0), "一条功能间依赖都没扫到,八成是正则或目录写错了").toBe(true);
  });
});
