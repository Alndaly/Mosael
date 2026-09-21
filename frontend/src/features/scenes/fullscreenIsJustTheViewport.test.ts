/**
 * 3D 页的「全屏」= **只看这个 3D 视图**。
 *
 * 此前它只是把整个编辑器铺满屏幕 —— 页头、时间线、属性栏、智能体栏一样不少,于是"全屏"和
 * "最大化窗口"没有区别,而人按它是想把画面看大。按钮本来就长在视口自己那条工具栏上。
 *
 * 这条测试同时盯住**两侧**:样式里写了要藏哪几块,而那几个类名必须在 SceneStudio 里真的用着。
 * 只测 CSS 的话,类名打错一个字母就是"藏了个不存在的东西" —— 样式表看着没问题,全屏下那一栏
 * 照样在,而没有任何东西会报错。
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./scenes.css", import.meta.url), "utf8");
const studio = readFileSync(new URL("./SceneStudio.tsx", import.meta.url), "utf8");

/** 全屏下要收起来的那几块。 */
const HIDDEN = [
  "scene-header",
  "scene-side",
  "scene-timeline",
  "scene-agent-dock",
  "scene-agent-floating",
  "scene-resize-side",
  "scene-resize-agent",
];

function fullscreenBlock(): string {
  // `.scene-studio[data-screen-mode]` 开头的那几条规则,直到下一个不带它的选择器为止。
  const parts = css.split("\n\n").filter((block) => block.includes("[data-screen-mode]"));
  return parts.join("\n");
}

describe("3D 页全屏", () => {
  const block = fullscreenBlock();

  it.each(HIDDEN)("收起 %s", (klass) => {
    // 直接子代(`> .scene-header`)和后代选择器都算。
    expect(block).toMatch(new RegExp(`\\[data-screen-mode\\] (> )?\\.${klass}[,\\s{]`));
  });

  it("收起来的每个类名都真的用在 SceneStudio 上", () => {
    // 打错一个字母 = 藏了个不存在的东西:样式表看着没问题,那一栏照样在。
    const missing = HIDDEN.filter((klass) => !studio.includes(klass));
    expect(missing).toEqual([]);
  });

  it("侧栏藏了,网格也要退回单栏 —— 否则右边空出一大块", () => {
    expect(block).toMatch(/\.scene-studio\[data-screen-mode\] \.scene-workspace \{[^}]*grid-template-columns: 1fr/);
  });

  it("视口自己那条工具栏留着 —— 退出的按钮在上面", () => {
    expect(block).not.toContain(".scene-stage-bar");
    expect(studio).toContain("退出全屏");
  });
});

describe("页头和它下面那一行之间要有线", () => {
  it(".scene-header 画下边线", () => {
    // 工作区那边刻意不画上边线(理由写在 .scene-workspace 上:"上面已经有一条"),
    // 而页头这边此前也没画 —— 于是一条都没有,标题行和视角切换行糊成一块。
    const header = css.slice(css.indexOf(".scene-header {"));
    const body = header.slice(0, header.indexOf("}"));
    expect(body).toContain("border-bottom: 1px solid var(--divider)");
  });
});
