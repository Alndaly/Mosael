/** @vitest-environment jsdom */
import React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentStatusRow } from "./AgentStatusRow";
import { AGENT_ROW_CLASS } from "./agentRow";

describe("「还在跑」那一行", () => {
  /**
   * 工具行的耗时排在自己那一栏的右缘,上下几行对齐成一列。而这一行此前是
   * 「智能体思考中… 已用 1.0s」两截贴着写 —— 读起来像半句话,和上面每一行的耗时都对不上。
   */
  it("耗时靠右,中间由可伸缩的空白撑开", () => {
    const { container } = render(<AgentStatusRow label="智能体思考中…" meta="已用 1.0s" />);
    const content = container.querySelector('[data-slot="marker-content"]')!;
    const kids = [...content.children];
    expect(kids).toHaveLength(3); // 文案、占位、耗时
    expect(kids[0].textContent).toBe("智能体思考中…");
    expect(kids[1].getAttribute("aria-hidden")).toBe("true");
    expect(kids[1].className).toContain("flex-1");
    expect(kids[2].textContent).toBe("已用 1.0s");
    expect(kids[2].className).toContain("flex-none");
  });

  it("正文已经在流的时候不再说一遍「在思考」,只剩耗时", () => {
    const { container } = render(<AgentStatusRow meta="已用 3.2s" />);
    const kids = [...container.querySelector('[data-slot="marker-content"]')!.children];
    expect(kids).toHaveLength(2);
    expect(kids[1].textContent).toBe("已用 3.2s");
  });

  it("和工具行、思考行共用同一份行几何", () => {
    // 四个调用点此前各写了一份:有的没有内缩、有的字号从外层继承成 text-ui-md。
    const { container } = render(<AgentStatusRow meta="已用 1.0s" />);
    const marker = container.querySelector('[data-slot="marker"]')!;
    for (const one of AGENT_ROW_CLASS.split(" ")) expect(marker.className).toContain(one);
  });
});
