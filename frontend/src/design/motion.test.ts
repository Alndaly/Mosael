/**
 * 动效只用一套刻度,并且尊重「减少动态」。
 *
 * 盘点时全站的过渡时长有 100、120、140、150、160、180、200、250、260、300、700 毫秒十一种,缓动有 ease、ease-out、
 * ease-in、Tailwind 默认的 ease-in-out 和一条手写的 cubic-bezier —— 同样是「浮层出现」,菜单 150ms、抽屉 250ms、
 * 遮罩 200ms;同样是「悬停换底色」,有的 120ms 有的 150ms 有的 180ms。单看哪一处都说得过去,放在一起就是一屏东西各按
 * 各的节奏动。刻度见 design/tokens.css 里 `--ease-enter` 上面那段说明和 docs/CONVENTIONS.md「动效」。
 *
 * 这条盯三件事:
 * - **时长在刻度上**:源码里的 `duration-N`(含 `duration-[Nms]`、带变体前缀的)和样式表里 `transition` 写的毫秒数,
 *   只能是 0 / 100 / 160 / 240 / 600;样式表里一次性的 `--animate-*` 用 `var(--motion-*)`。
 * - **减少动态时循环的停下**:全局那条规则除了压时长,还得把循环次数压成 1 —— 只压时长的话,循环动画 0.01ms 一圈,
 *   停在随便哪个相位上(转圈的图标歪着、呼吸的浮标半涨开)。
 * - **转圈是例外**:它是「还在做」的唯一信号,减少动态时放慢、不停。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { blankComments } from "@/design/jsxSource";

const SRC = join(import.meta.dirname, "..");
const SCALE = new Set([0, 100, 160, 240, 600]);

/**
 * 还没换到刻度上的。只许减少。
 * 现在一个不剩:失败卡随共用失败组件那一批、创作页的会话列表和生成区随 ADR 0052 那一批都收到了刻度上。
 */
const KNOWN = new Set<string>([]);

function sources(ext: RegExp): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(full);
      return ext.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [relative(SRC, full)] : [];
    });
  return walk(SRC).sort();
}

const lineOf = (code: string, index: number) => code.slice(0, index).split("\n").length;
const stripCssComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "));

/** 一个时长写法换成毫秒:`160`(Tailwind 的数字就是毫秒)、`[120ms]`、`0.01ms`、`1.6s`。 */
function millis(value: string): number {
  const bare = value.replace(/^\[|\]$/g, "");
  if (/^[\d.]+$/.test(bare)) return Number(bare);
  const match = /^([\d.]+)(ms|s)$/.exec(bare);
  if (!match) return Number.NaN;
  return Number(match[1]) * (match[2] === "s" ? 1000 : 1);
}

function offScaleInSource(): string[] {
  const found: string[] = [];
  for (const rel of sources(/\.(ts|tsx)$/)) {
    const code = blankComments(readFileSync(join(SRC, rel), "utf8"));
    for (const match of code.matchAll(/(?<![\w-])duration-(\[[\d.]+m?s\]|\d+)(?![\w-])/g)) {
      if (!SCALE.has(millis(match[1]))) found.push(`${rel}:${lineOf(code, match.index)} duration-${match[1]}`);
    }
  }
  return found;
}

/** 样式表里 `transition` / `transition-duration` 写死的时长(要求减少动态那几块压成一瞬的不算 —— 它们就是「没有动效」)。 */
function offScaleInStylesheets(): string[] {
  const found: string[] = [];
  for (const rel of sources(/\.css$/)) {
    const css = stripCssComments(readFileSync(join(SRC, rel), "utf8"));
    for (const match of css.matchAll(/(?<![\w-])transition(?:-duration)?\s*:([^;}]*)/g)) {
      for (const time of match[1].matchAll(/(?<![\w-])([\d.]+m?s)\b/g)) {
        const ms = millis(time[1]);
        if (ms > 0 && ms < 1) continue;
        if (!SCALE.has(ms)) found.push(`${rel}:${lineOf(css, match.index)} ${time[1]}`);
      }
    }
  }
  return found;
}

const TOKENS = stripCssComments(readFileSync(join(SRC, "design/tokens.css"), "utf8"));

/** tokens.css 里所有 `@media (prefers-reduced-motion: reduce) { … }` 块的内容。 */
function reducedMotionBlocks(): string[] {
  const blocks: string[] = [];
  for (const match of TOKENS.matchAll(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{/g)) {
    let depth = 1;
    let i = match.index + match[0].length;
    const start = i;
    while (i < TOKENS.length && depth > 0) {
      if (TOKENS[i] === "{") depth += 1;
      else if (TOKENS[i] === "}") depth -= 1;
      i += 1;
    }
    blocks.push(TOKENS.slice(start, i - 1));
  }
  return blocks;
}

/** 一块里某个选择器的声明(第一条)。 */
function ruleBody(block: string, selector: RegExp): string | null {
  const match = new RegExp(`${selector.source}\\s*\\{([^}]*)\\}`).exec(block);
  return match ? match[1] : null;
}

describe("动效刻度", () => {
  it("源码里的 duration-* 都在刻度上(0 / 100 / 160 / 240 / 600)", () => {
    const fresh = offScaleInSource().filter((line) => !KNOWN.has(line.split(":")[0]));
    expect(fresh).toEqual([]);
  });

  it("样式表里 transition 写的时长都在刻度上", () => {
    expect(offScaleInStylesheets()).toEqual([]);
  });

  it("tokens.css 里一次性的动画(不循环的 --animate-*)用 var(--motion-*) 定时长", () => {
    const loose = [...TOKENS.matchAll(/--animate-([\w-]+):([^;]*);/g)]
      .filter((match) => !/\binfinite\b/.test(match[2]) && !/var\(--motion-(fast|base|slow|linger)\)/.test(match[2]))
      .map((match) => `--animate-${match[1]}:${match[2]}`);
    expect(loose).toEqual([]);
  });

  it("存量清单只减不增:清单里的文件确实还有刻度外的时长", () => {
    const stillOff = new Set(offScaleInSource().map((line) => line.split(":")[0]));
    expect([...KNOWN].filter((rel) => !stillOff.has(rel))).toEqual([]);
  });

  it("扫得到东西:刻度上的写法确实被认出来", () => {
    // 防扫描器失灵后一片空白地「通过」:全站至少有几十处 duration-100 / duration-160。
    const all = sources(/\.(ts|tsx)$/)
      .map((rel) => readFileSync(join(SRC, rel), "utf8"))
      .join("\n");
    expect((all.match(/(?<![\w-])duration-(100|160)(?![\w-])/g) ?? []).length).toBeGreaterThan(30);
    expect(millis("[120ms]")).toBe(120);
    expect(millis("1.6s")).toBe(1600);
  });
});

describe("减少动态", () => {
  const globalRule = () =>
    reducedMotionBlocks()
      .map((block) => ruleBody(block, /\*,\s*\*::before,\s*\*::after/))
      .find((body): body is string => body !== null) ?? "";

  it("全局那条把动画、过渡压成一瞬,并且循环的只走一遍", () => {
    const body = globalRule();
    expect(body).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(body).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
    expect(body).toMatch(/animation-iteration-count:\s*1\s*!important/);
  });

  it("转圈例外:放慢、照样循环", () => {
    const spinner = reducedMotionBlocks()
      .map((block) => ruleBody(block, /\.animate-mosael-spin,\s*\.animate-spin/))
      .find((body): body is string => body !== null);
    expect(spinner).toBeTruthy();
    expect(spinner).toMatch(/animation-iteration-count:\s*infinite\s*!important/);
    expect(millis(/animation-duration:\s*([\d.]+m?s)/.exec(spinner ?? "")?.[1] ?? "")).toBeGreaterThanOrEqual(1000);
  });
});
