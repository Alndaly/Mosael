/**
 * 同级元素之间的间距(`gap`)只用一套刻度。
 *
 * 仓库的 UI 规矩是「段间 12 / 块间 8 / 行内 4,出现第四个数就是错的」。
 * 2026-11 的 UI 走查扫出来 gap 上用了二十来种值:10px、14px、3/5/7/9px 这类各写各的,还有 16–40px 的页面级间距。
 * 当时把 10/14 和零散的像素值就近收进了刻度(差 1–2px,看不出来);16px 以上的那批改了会动版面,
 * 留给逐页的设计决定,记在 `spacingScale.baseline.json` 里。
 *
 * **刻度**(Tailwind 一档 = 4px):
 * - 布局:`gap-1` 4 / `gap-2` 8 / `gap-3` 12;
 * - 控件内部的图标与文字:`gap-0.5` 2 / `gap-1.5` 6 —— 那是控件自己的排版,不是版面节奏;
 * - `gap-0`、`gap-px` 是「贴着」,不算间距。
 *
 * 样式表里的 `gap: Npx` 是同一件事的另一种写法,一起看(刻度同上:0/2/4/6/8/12)。
 *
 * **这是一道棘轮**:不在基线里的文件一处都不许有;在基线里的文件只许变少。
 * 改少了要把基线跟着降 —— `UPDATE_SPACING_BASELINE=1 pnpm vitest run src/design/spacingScale.test.ts` 重写那份 JSON。
 */

// 这条测试是一道棘轮:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const BASELINE_FILE = join(import.meta.dirname, "spacingScale.baseline.json");

/** Tailwind 的 gap 档位里,刻度内的那几档。 */
const ON_SCALE_STEPS = new Set(["0", "px", "0.5", "1", "1.5", "2", "3"]);
/** 样式表里刻度内的像素值。 */
const ON_SCALE_PX = new Set(["0", "2px", "4px", "6px", "8px", "12px"]);

const TAILWIND_GAP = /(?<![-\w])gap(?:-[xy])?-(\[[^\]]+\]|[\d.]+|px)(?![\w.-])/g;
const CSS_GAP = /(?<![-\w])gap:\s*([\d.]+(?:px)?)/g;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    if (entry.name.includes(".test.")) return [];
    return /\.(ts|tsx|css)$/.test(entry.name) ? [full] : [];
  });
}

/** 每个文件里刻度外的 gap 有几处(没有的文件不出现)。 */
function offScaleCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    const values = file.endsWith(".css")
      ? [...text.matchAll(CSS_GAP)].map((one) => one[1]).filter((value) => !ON_SCALE_PX.has(value))
      : [...text.matchAll(TAILWIND_GAP)].map((one) => one[1]).filter((value) => !ON_SCALE_STEPS.has(value));
    if (values.length > 0) counts[relative(SRC, file)] = values.length;
  }
  return counts;
}

function readBaseline(): Record<string, number> {
  return JSON.parse(readFileSync(BASELINE_FILE, "utf8")) as Record<string, number>;
}

describe("间距刻度", () => {
  it("刻度外的 gap 只许变少:新文件一处都不许有,基线里的文件不许多", () => {
    const actual = offScaleCounts();
    if (process.env.UPDATE_SPACING_BASELINE) {
      const sorted = Object.fromEntries(Object.entries(actual).sort(([a], [b]) => a.localeCompare(b)));
      writeFileSync(BASELINE_FILE, `${JSON.stringify(sorted, null, 2)}\n`);
      return;
    }
    const baseline = readBaseline();
    const grew = Object.entries(actual)
      .filter(([file, count]) => count > (baseline[file] ?? 0))
      .map(([file, count]) => `${file}: ${count} 处(基线 ${baseline[file] ?? 0})`);
    expect(grew, "间距用 gap-1 / gap-2 / gap-3(控件内部图标与文字可用 gap-0.5 / gap-1.5)").toEqual([]);
  });

  it("基线跟着收紧:改少了的文件要把基线降下来", () => {
    if (process.env.UPDATE_SPACING_BASELINE) return;
    const actual = offScaleCounts();
    const stale = Object.entries(readBaseline())
      .filter(([file, count]) => (actual[file] ?? 0) < count)
      .map(([file, count]) => `${file}: 基线 ${count},实际 ${actual[file] ?? 0}`);
    expect(stale, "用 UPDATE_SPACING_BASELINE=1 重写 spacingScale.baseline.json").toEqual([]);
  });

  it("扫描面里有样式表也有组件 —— 别变成只扫一种", () => {
    const files = sourceFiles(SRC);
    expect(files.some((one) => one.endsWith(".css"))).toBe(true);
    expect(files.some((one) => one.endsWith(".tsx"))).toBe(true);
  });
});
