import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 吸顶栏的底色**跟着"有没有东西从下面滚过去"淡入淡出**。
 *
 * 这条钉两件事:一是它不能是突变(用户看到的是"啪"地铺上一层底),二是它不能只在磨砂外观下
 * 成立 —— 此前底色写了两份,只有磨砂那份认得 `data-stuck`,于是同一条筛选栏,开了磨砂会跟着
 * 滚动淡入,不开就一直铺着实底,把自定义背景切掉一条。
 */
const css = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8");
const media = readFileSync(
  join(import.meta.dirname, "../features/media/MediaLibraryView.tsx"),
  "utf8",
);

/** 取一条规则的声明块。 */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)\\s*${escaped} \\{([\\s\\S]*?)\\n\\s*\\}`));
  if (!match) throw new Error(`Missing rule ${selector}`);
  return match[1];
}

describe("吸顶栏", () => {
  it("没滚动时透明,吸住时才铺底 —— 开关是 data-stuck", () => {
    expect(rule(".workspace-sticky")).toContain("--workspace-sticky-presence: 1");
    expect(rule('.workspace-sticky[data-stuck="false"]')).toContain("--workspace-sticky-presence: 0");
  });

  it("底色和分割线都按 presence 混,一起淡入", () => {
    // 分割线分的是"栏"和"从底下滚过去的内容";没有内容滚过去时,它分的是空气。
    const painted = rule(".workspace-sticky[data-stuck]");
    for (const property of ["background-color", "border-color"]) {
      expect(painted).toContain(property);
    }
    expect(painted.match(/var\(--workspace-sticky-presence\)/g)?.length).toBe(2);
  });

  it("是过渡,不是突变", () => {
    const transition = /transition:([\s\S]*?);/.exec(rule(".workspace-sticky"))?.[1] ?? "";
    for (const property of ["--workspace-sticky-presence", "background-color", "border-color"]) {
      expect(transition).toContain(property);
    }
    expect(transition).toMatch(/\d+ms/);
    // 要求减少动效的人拿到的是瞬时切换,而不是"没有底色"。
    expect(css).toMatch(/prefers-reduced-motion[\s\S]*?\.workspace-sticky \{ transition-duration: 0ms/);
  });

  it("跟着滚动淡入的栏不许有自己的 backdrop-filter —— 恒等滤镜也不行", () => {
    /*
     * 这条钉的是那条"底色明明全透明,页面上却横着一条平板色带"的 bug。
     *
     * 任何非 none 的 backdrop-filter 都会让元素成为一个 backdrop root,而它只看得见**外层
     * backdrop root 内部**画了什么。内容区(main)自己就是一层磨砂,自定义背景图在它后面 ——
     * 于是这条栏取到的"背景"是内容区那层 72% 的实底,背景图整个丢掉。`blur(0px)` 同样算数:
     * 恒等滤镜不是免费的。
     */
    expect(() => rule(':root[data-appearance="glass"] .workspace-sticky')).toThrow();
    const alwaysStuck = rule(':root[data-appearance="glass"] .workspace-sticky:not([data-stuck])');
    expect(alwaysStuck).toContain("backdrop-filter");
    expect(css).not.toMatch(/\.workspace-sticky\[data-stuck[^{]*\{[^}]*backdrop-filter/);
  });

  it("吸住时是实色 —— 它得自己盖住底下滚过去的卡片,没有模糊可以指望", () => {
    expect(rule(".workspace-sticky[data-stuck]")).toContain("var(--surface-solid)");
    // --surface-solid 不跟着磨砂被调透,否则"吸住时变为不透明"在磨砂下就不成立。
    for (const theme of [":root", ".dark"] as const) {
      expect(rule(theme)).toMatch(/--surface-solid:\s*#[0-9a-f]{6}/i);
    }
    expect(css).not.toMatch(/data-appearance="glass"[^{]*\{[^}]*--surface-solid/);
  });

  it("素材筛选栏交出 data-stuck,而且不自己写死底色", () => {
    // 写死一个 bg-* 会盖过那条规则(它无层级,压得住工具类),等于把开关按住不放。
    const bar = /<div ref=\{filtersRef\}[^>]*className="([^"]*)"/.exec(media)?.[1];
    expect(bar, "找不到素材筛选栏").toBeTruthy();
    expect(bar).toContain("workspace-sticky");
    expect(media).toContain("data-stuck={filtersStuck}");
    expect(bar).not.toMatch(/\bbg-\S+/);
  });
});
