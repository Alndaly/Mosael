/** @vitest-environment jsdom */
/**
 * 高亮的 token 颜色必须走 CSS 变量,**不能写成内联 `color`**。
 *
 * 这条防的 bug 在浅色模式下完全看不出来,所以它活了很久:shiki 双主题模式给的 `htmlStyle`
 * 长这样 —— `{ color: "#24292e", "--shiki-dark": "#E1E4E8" }`。整个摊进 style 的话,那个
 * 内联 `color` 会压过 `dark:text-[var(--shiki-dark)]`(内联样式赢过任何 class 规则),于是
 * `--shiki-dark` 设上了却没人读。浅色下碰巧是对的(内联色正好就是浅色),深色下拿到的是浅色
 * 主题的字色:真机实测 34 个 token 全部低于 4.5 对比度,最差 1.17 —— 基本看不见。
 *
 * 判据是**内联样式里不许出现 color**,而不是"看起来对不对":颜色对不对要有主题上下文才能判,
 * 而"有没有把切换权交出去"是一个当场可查的事实。
 */
import { render } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const highlight = vi.fn();
vi.mock("@/components/agent/codeHighlighter", () => ({
  codeHighlighter: {
    supportsLanguage: () => true,
    getThemes: () => ({ light: "github-light", dark: "github-dark" }),
    highlight: (...args: unknown[]) => highlight(...args),
  },
}));

import { HighlightedCode } from "@/components/agent/HighlightedCode";

/** shiki 在 defaultColor:"light" 下真实给出的形状。 */
const DUAL_THEME_TOKEN = {
  content: '"task"',
  htmlStyle: { color: "#24292e", "--shiki-dark": "#E1E4E8" },
};

beforeEach(() => highlight.mockReset());

describe("token 配色的落点", () => {
  it("不把 color 写进内联样式 —— 那会压掉暗色变体", () => {
    highlight.mockReturnValue({ tokens: [[DUAL_THEME_TOKEN]] });
    const { container } = render(<HighlightedCode code='{"task":1}' />);
    const span = container.querySelector("pre span") as HTMLElement;

    expect(span, "没有渲染出 token").toBeTruthy();
    expect(span.style.color, "内联 color 会压过 dark: 变体,暗色主题永远生效不了").toBe("");
  });

  it("亮色值搬到 --sdm-c,暗色值原样留着", () => {
    highlight.mockReturnValue({ tokens: [[DUAL_THEME_TOKEN]] });
    const { container } = render(<HighlightedCode code='{"task":1}' />);
    const span = container.querySelector("pre span") as HTMLElement;

    expect(span.style.getPropertyValue("--sdm-c")).toBe("#24292e");
    expect(span.style.getPropertyValue("--shiki-dark")).toBe("#E1E4E8");
  });

  it("两个变量都由 class 去读,明暗各取一个", () => {
    highlight.mockReturnValue({ tokens: [[DUAL_THEME_TOKEN]] });
    const { container } = render(<HighlightedCode code='{"task":1}' />);
    const span = container.querySelector("pre span") as HTMLElement;

    expect(span.className).toContain("var(--sdm-c");
    expect(span.className).toContain("dark:text-[var(--shiki-dark");
  });

  it("单主题模式(颜色在 token.color 上)也照样搬到 --sdm-c", () => {
    highlight.mockReturnValue({ tokens: [[{ content: "x", color: "#D73A49" }]] });
    const { container } = render(<HighlightedCode code="x" />);
    const span = container.querySelector("pre span") as HTMLElement;

    expect(span.style.getPropertyValue("--sdm-c")).toBe("#D73A49");
    expect(span.style.color).toBe("");
  });
});
