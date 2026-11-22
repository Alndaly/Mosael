import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const MAIN = fs.readFileSync(path.resolve(__dirname, "main.cjs"), "utf8");
const STYLES = ["../frontend/src/design/tokens.css", "../frontend/src/features/editor/editor.css"].map((file) => ({
  file,
  css: fs.readFileSync(path.resolve(__dirname, file), "utf8"),
}));

describe("Windows / Linux 上的滚动条不占宽度", () => {
  /**
   * 维护者:「Windows 上可滚动部分的右侧滚动条出现的时候会占据额外位置,导致页面 UI 宽度变动 …… 在 macOS 上则不会」。
   * Windows / Linux 默认是占布局宽度的经典滚动条;桌面壳打开 Chromium 的 `OverlayScrollbar` 让它们悬浮在内容上。
   * 此前开关写成复数 `OverlayScrollbars` —— Chromium 没有这个特性,开关一直是空的。
   */
  it("非 macOS 打开的是单数的 OverlayScrollbar 特性,在 app ready 之前", () => {
    const at = MAIN.indexOf('app.commandLine.appendSwitch("enable-features", "OverlayScrollbar")');
    expect(at).toBeGreaterThan(-1);
    expect(MAIN).not.toMatch(/appendSwitch\("enable-features",\s*"OverlayScrollbars"\)/);
    expect(MAIN.slice(Math.max(0, at - 60), at)).toContain('process.platform !== "darwin"');
    expect(at).toBeLessThan(MAIN.indexOf("app.requestSingleInstanceLock()"));
  });

  /**
   * Chromium 只把**没自定义样式**的滚动条画成悬浮的:一设 `scrollbar-width` / `scrollbar-color` 就退回占宽度的经典条,
   * 全局那套「悬停时 none → thin」于是在 Windows 上把内容挤窄再弹回。所以这些声明只能落在 macOS 与网页版上 ——
   * 规则的选择器必须带着 `:root:not(.is-desktop.is-win)`(`.is-win` 就是非 macOS 的桌面版,见 lib/windowChrome)。
   */
  it("样式表里给滚动条设宽度 / 颜色的规则都限定在 Windows / Linux 桌面版之外", () => {
    const offenders: string[] = [];
    for (const { file, css } of STYLES) {
      const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
      for (const rule of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const [, selector, body] = rule;
        if (!/scrollbar-(width|color)\s*:/.test(body)) continue;
        const parts = selector.split(",").map((part) => part.trim());
        for (const part of parts) {
          if (!part.includes(":root:not(.is-desktop.is-win)")) offenders.push(`${file}: ${part}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
