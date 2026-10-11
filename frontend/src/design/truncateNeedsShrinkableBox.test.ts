/**
 * 字段名 / 表单名外面那一层必须能收缩 —— 否则 `Truncate` 拿不到宽度,长名字被硬裁掉、连省略号都没有。
 *
 * 维护者截图:表单字段那个设置浮层里,名字长过面板就被面板边缘切掉,没有省略号。
 * 量出来的原因:面板是 `grid w-80`(320px),而名字外面还套了一层 `<span>` —— **那层才是 grid 子项**;
 * 它的 `min-width` 是 `auto`,不肯收缩,于是那一格 326px > 面板 320px,里面的 `Truncate` 宽度等于文字宽度
 * (clientWidth == scrollWidth),`text-overflow: ellipsis` 永远不会生效。给外层加 `min-w-0` 之后那一格是
 * 296px(client 296 < scroll 326),省略号出来了。
 *
 * `Truncate` 自己带 `min-w-0`(见 components/ui/truncate 的说明),所以:
 *
 * - `Truncate` **自己**是那个 flex/grid 子项(它带 `min-w-0` 或 `flex-1`)→ 合规;
 * - 外面套了一层 → 那一层要写 `min-w-0`;它是 `flex` / `grid` **容器**时,收缩交给里面的子项,也算合规。
 *
 * jsdom 没有排版,量不了宽,所以这条按源码判 —— 和设计表里别的几条一样的做法。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/** 这一组里名字的长度不由我们定:节点名、字段名、表单名(工作流里叫什么就是什么)。 */
const FOLDER = join(import.meta.dirname, "..", "features", "plugins", "appForm");

const OPENING_WITH_TRUNCATE = /<([a-zA-Z][\w.]*)((?:\s+[^<>]*?)?)>\s*<Truncate((?:\s+[^<>]*?)?)>/g;

function classes(source: string): string {
  const found = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{cn\(([^)]*)\))/.exec(source);
  return found ? found[1] ?? found[2] ?? found[3] ?? "" : "";
}

function shrinkable(value: string): boolean {
  //: `min-w-0` 直接写出来,或者那一层本身就是容器 —— 容器不参与"谁被压扁",收缩落在它的子项上。
  return /(?:^|\s)min-w-0(?:\s|$)/.test(value) || /(?:^|\s)(?:flex|grid)(?:\s|$)/.test(value);
}

function offenders(): string[] {
  const found: string[] = [];
  for (const name of readdirSync(FOLDER)) {
    if (!name.endsWith(".tsx") || name.includes(".test.")) continue;
    const source = readFileSync(join(FOLDER, name), "utf8");
    for (const match of source.matchAll(OPENING_WITH_TRUNCATE)) {
      const [, tag, attrs, truncateAttrs] = match;
      if (!/^[a-z]/.test(tag)) continue;
      const outer = classes(attrs);
      const inner = classes(truncateAttrs);
      //: `Truncate` 自己就是那一格(它带 min-w-0 / flex-1)时不用管外层。
      if (shrinkable(outer) || /(?:^|\s)(?:min-w-0|flex-1)(?:\s|$)/.test(inner)) continue;
      const line = source.slice(0, match.index).split("\n").length;
      found.push(`${name}:${line}  <${tag} className="${outer.trim()}">`);
    }
  }
  return found;
}

describe("字段名外面那一层能收缩", () => {
  it("没有哪一处让 Truncate 悬在不收缩的格子里", () => {
    expect(offenders(), "给外面那一层加 min-w-0(见本文件开头)").toEqual([]);
  });
});
