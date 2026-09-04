/**
 * 同级元素的重复间距只由父容器控制。
 *
 * `space-y-*`/`space-x-*` 是靠给子元素补 margin 实现的；一旦子组件自己又带 `mt`/`mb`，
 * 两套间距就会叠加，而且插入条件节点后节奏还会变化。统一使用 flex/grid 的 `gap`，让同级元素
 * 只有一个间距来源。组件内部的 padding 仍由组件自己拥有，并由各组件的组合契约测试约束；
 * 负值的 `-space-x-*` 用于头像叠放，不属于布局间距，继续允许。
 */

// 这条测试是一道棘轮:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.includes(".test.") ? [full] : [];
  });
}

describe("布局间距", () => {
  it("同级元素使用父容器 gap，不使用会给子元素追加 margin 的正向 space 工具类", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      for (const match of readFileSync(file, "utf8").matchAll(/(?<!-)space-[xy]-[^\s"'`]+/g)) {
        offenders.push(`${file.slice(SRC.length + 1)} → ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
