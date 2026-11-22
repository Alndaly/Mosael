/**
 * 管理页节头(`AdminSection` 的 `actions`)里的按钮和页面工具栏同高:40px 的 `default` 档。
 *
 * 管理页的节标题是小号字(text-ui-md),节头下面紧跟 40px 的搜索框、筛选下拉和列表。
 * 节头按钮曾经一律是 32px 的 `sm`,和下面那排控件一高一矮。维护者看成本规则那一节:
 * 「第一排的按钮的高度是否和正常按钮不太一致,太矮了」。
 *
 * 设置页的节头不在此列:它的节标题是 20px 的大号字,按钮在标题旁边、下面先隔一条分隔线,
 * 卡片模式又正是约定里 `sm` 的「卡片」那一档。
 *
 * 判据:`features/admin` 里每个 `actions={…}` 块(花括号配平取整块)不许出现小一档的尺寸。
 */

// 这条测试是一道棘轮:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ADMIN = join(import.meta.dirname, "..", "features", "admin");
const SMALLER_SIZE = /size="(sm|xs|icon-sm|icon-xs)"/g;

/** 每个 `actions={` 后面配平的那一整块。 */
function actionBlocks(source: string): string[] {
  const blocks: string[] = [];
  for (const match of source.matchAll(/actions=\{/g)) {
    let index = match.index + match[0].length;
    let depth = 1;
    while (depth > 0 && index < source.length) {
      if (source[index] === "{") depth += 1;
      if (source[index] === "}") depth -= 1;
      index += 1;
    }
    blocks.push(source.slice(match.index, index));
  }
  return blocks;
}

function sectionFiles(): string[] {
  return readdirSync(ADMIN)
    .filter((name) => name.endsWith(".tsx") && !name.includes(".test."))
    .map((name) => join(ADMIN, name))
    .filter((file) => readFileSync(file, "utf8").includes("<AdminSection"));
}

describe("管理页节头按钮", () => {
  it("和页面工具栏同高:节头 actions 里不用 sm / xs", () => {
    const offenders = sectionFiles().flatMap((file) =>
      actionBlocks(readFileSync(file, "utf8")).flatMap((block) =>
        [...block.matchAll(SMALLER_SIZE)].map((one) => `${file.slice(ADMIN.length + 1)} → ${one[0]}`),
      ),
    );
    expect(offenders).toEqual([]);
  });

  it("扫描面确实覆盖到带节头按钮的那几节 —— 别变成什么都没扫", () => {
    const withActions = sectionFiles().filter((file) => actionBlocks(readFileSync(file, "utf8")).length > 0);
    expect(withActions.length).toBeGreaterThanOrEqual(5);
  });
});
