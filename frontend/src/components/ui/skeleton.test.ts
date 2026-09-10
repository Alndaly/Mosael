import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 加载占位块的底色必须**相对它所在的那层表面**算,不能是一个固定的灰。
 *
 * 此前是 `bg-muted` —— 页面的次级底色。而占位块也出现在弹层上(插件市场就在 ModalShell 里),
 * 弹层的表面比页面**更浅**,于是两者几乎同色:实测对比 1.07(浅色)/ 1.14(深色),再叠上
 * animate-pulse 的透明度起伏,眼睛完全看不出那儿有东西。用户报的「加载中没有 Skeleton」
 * 其实是有,只是看不见。
 *
 * 换成前景色的低透明度叠加之后,三种表面(页面 / 卡片 / 弹层)上都是同一个相对差:
 * 实测 1.25–1.26(浅色)、1.38–1.42(深色)。
 *
 * jsdom 不做颜色合成,所以这里钉的是**取色的方式**,不是最终对比度。
 */
/** 去掉注释 —— 那段注释里正写着"此前是 bg-muted",不去掉的话这条棘轮会被自己的说明喂饱。 */
const source = readFileSync(join(import.meta.dirname, "skeleton.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

describe("加载占位块", () => {
  it("底色是前景色的低透明度叠加 —— 合成在当前这层上", () => {
    expect(source).toMatch(/bg-foreground\/\[?0?\.\d+\]?/);
  });

  it("不吃任何一个固定的表面 token", () => {
    // 这些都是"某一层"的底色:占位块一旦踩到别的层上就没了。
    for (const token of ["bg-muted", "bg-secondary", "bg-card", "bg-popover", "bg-accent"]) {
      expect(source, `${token} 是某一层自己的底色,不能拿来当占位块`).not.toContain(token);
    }
  });

  it("会脉冲 —— 静止的灰块读起来像一块空布局,不像「内容在来的路上」", () => {
    expect(source).toContain("animate-pulse");
  });
});
