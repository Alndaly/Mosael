import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { FLOATING_SURFACE, MODAL_SURFACE } from "@/components/ui/floating";

/**
 * 分隔线在**每一层表面上**都得看得见。
 *
 * 起因是一张截图:笔记的右键菜单明明分了四组(组与组之间有空当),可一条线都没有。
 * 线是画了的 —— `--popover: #292c30` 对 `--divider: #292d33`,差 (0,1,3),对比 **1.013**。
 * 页面上同一条线是 1.32,到了菜单里等于没画。
 *
 * 所以这里量的不是"有没有写 border",是**对比够不够**:页面色只保证踩在页面上好看,
 * 浮层/弹窗自己得把 `--divider` 换成贴着这层算的那一版。哪天有人调 `--popover` 或
 * `--foreground`,这几条会先红。
 */

/** 注释先剥掉:这个文件的注释里就写着 `--divider: #292d33` 之类的字面值,不剥就是自己喂自己。 */
const CSS = fs.readFileSync(path.join(__dirname, "tokens.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

/** 取某个块(`:root` / `.dark`)里声明的字面色值。只认 `#rrggbb`,派生值不在这条测试的范围内。 */
function palette(selector: string): Record<string, string> {
  const start = CSS.indexOf(`\n${selector} {`);
  expect(start, `tokens.css 里找不到 ${selector}`).toBeGreaterThan(-1);
  const end = CSS.indexOf("\n}", start);
  const block = CSS.slice(start, end);
  const out: Record<string, string> = {};
  for (const [, name, value] of block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out[name] = value.toLowerCase();
  }
  return out;
}

const rgb = (hex: string) =>
  [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

const channel = (v: number) => {
  const s = v / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};

const luminance = (hex: string) => {
  const [r, g, b] = rgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
};

const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/** `color-mix(in srgb, fg alpha%, transparent)` 画在 bg 上之后的实际颜色。 */
const composite = (fg: string, bg: string, alpha: number) => {
  const f = rgb(fg);
  const b = rgb(bg);
  return `#${f.map((c, i) => Math.round(c * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
};

/** 发丝线的下限:比这更弱就是"看不出那儿有条线"。页面上现有最弱的一处是 1.11。 */
const MIN_HAIRLINE = 1.1;

/** tokens.css 里 .floating-surface/.modal-surface/.canvas-overlay-surface 用的那个透明度。 */
const SURFACE_DIVIDER_ALPHA = 0.08;

describe.each([
  ["浅色", ":root"],
  ["深色", ".dark"],
])("%s主题的分隔线", (_label, selector) => {
  const token = palette(selector);

  it.each([
    ["页面", "background"],
    ["卡片", "card"],
  ])("页面色画在%s上够得着", (_where, surface) => {
    expect(contrast(token[surface], token.divider)).toBeGreaterThan(MIN_HAIRLINE);
  });

  it.each([
    ["浮层", "popover"],
    ["弹窗", "modal-solid"],
    ["画布浮窗", "canvas-window-solid"],
  ])("%s上用的是贴着这层算的那一版,而不是页面色", (_where, surface) => {
    const onSurface = composite(token.foreground, token[surface], SURFACE_DIVIDER_ALPHA);
    expect(contrast(token[surface], onSurface)).toBeGreaterThan(MIN_HAIRLINE);
  });

});

/**
 * 那条覆盖是**承重的**,这条记的是它承的什么重:深色下页面色画在浮层上只有 1.013。
 *
 * 哪天有人把 `--popover` 或 `--divider` 调开了、这条自己变红,那是好消息 —— 说明覆盖可以连同
 * 这条测试一起删掉。在那之前,谁想省掉 tokens.css 里那三行,先得让这个数字过线。
 */
it("深色下页面色直接画到浮层上,弱到看不见 —— 覆盖不能删", () => {
  const dark = palette(".dark");
  expect(contrast(dark.popover, dark.divider)).toBeLessThan(MIN_HAIRLINE);
  expect(
    contrast(dark.popover, composite(dark.foreground, dark.popover, SURFACE_DIVIDER_ALPHA)),
  ).toBeGreaterThan(MIN_HAIRLINE);
});

describe("覆盖挂在哪儿", () => {
  it("三种表面共用一条规则,一处都不落下", () => {
    const rule = CSS.match(/([^{}]*)\{\s*--divider:\s*color-mix\([^;]*\);\s*\}/);
    expect(rule, "tokens.css 里没有给表面改写 --divider 的规则").not.toBeNull();
    for (const cls of [".floating-surface", ".canvas-overlay-surface", ".modal-surface"]) {
      expect(rule![1]).toContain(cls);
    }
  });

  /** 类名是覆盖的挂钩:从 FLOATING_SURFACE 里删掉它,菜单里的线就又没了。 */
  it("浮层和弹窗的外壳都带着那个挂钩类", () => {
    expect(FLOATING_SURFACE.split(" ")).toContain("floating-surface");
    expect(MODAL_SURFACE.split(" ")).toContain("modal-surface");
  });
});
