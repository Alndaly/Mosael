import { readFileSync } from "node:fs";

import { expect, it } from "vitest";

/** Windows 非系统全屏:灯箱的库工具条要和两颗浮钮一样让开原生窗口按钮。
 *
 * 只测 JSX 里的 className 抓不到这条:工具条是 react-photo-view 的 DOM,只能由全局 CSS 改。
 */
it("Windows 非系统全屏时,灯箱 BannerRight 让开 148px 原生窗口按钮区", () => {
  const css = readFileSync(new URL("../../app/styles.css", import.meta.url), "utf8");
  const rule = /\.is-desktop\.is-win:not\(\.is-fullscreen\) \.PhotoView-Slider__BannerRight\s*\{([^}]*)\}/.exec(css);
  expect(rule, "缺少 Windows 灯箱工具条避让规则").not.toBeNull();
  expect(rule![1].replace(/\s+/g, " ")).toContain("padding-right: calc(88px + 148px)");
});
