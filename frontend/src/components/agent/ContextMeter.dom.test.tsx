/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 上下文水位与压缩标记。
 *
 * 三条判据各自对应一个具体的误导:
 * 窗口未知时画进度条 → 没有分母的条会被读成"快满了";
 * 压缩静默进行 → 用户以为模型自己忘了早期内容;
 * 摘要为空时仍给展开 → 点开是一片空白,比不给展开更像坏了。
 */

// 带占位符的那几条要返回真实模板,否则 .replace("{n}", …) 无从发生,断言就成了空过。
const TEMPLATES: Record<string, string> = {
  agentContextLeft: "剩余 {n}%",
  agentCompacted: "移出 {n} 条,腾出 {saved}",
  agentContextPart_messages: "对话",
  agentContextPart_tools: "工具定义",
  agentContextPart_system: "系统提示",
  agentContextPart_free: "剩余",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { CompactionNotice, ContextBreakdown, ContextMeter, PART_COLORS } from "@/components/agent/ContextMeter";

describe("上下文水位", () => {
  it("窗口未知时整条不渲染", () => {
    const { container } = render(<ContextMeter context={{ tokens: 5000, window: 0 }} />);
    expect(container.textContent).toBe("");
    expect(render(<ContextMeter context={null} />).container.textContent).toBe("");
  });

  it("有窗口就一直显示 —— 用量低时也是有用的信息", () => {
    const { container } = render(<ContextMeter context={{ tokens: 20_000, window: 100_000 }} />);
    expect(container.textContent).toContain("80");
  });

  it("报剩余而不是已用,并在过线时转成告警色", () => {
    const { container, rerender } = render(<ContextMeter context={{ tokens: 60_000, window: 100_000 }} />);
    const bar = () => container.querySelector("[style*='width']") as HTMLElement;
    // 用户此刻在决定"还能不能接着问",剩余量是直接答案;已用量还要在脑子里做一次减法。
    expect(container.textContent).toContain("40");
    expect(bar().className).toContain("bg-primary");

    // 80% 是 sidecar 的触发阈值,到这条线就该显眼。
    rerender(<ContextMeter context={{ tokens: 85_000, window: 100_000 }} />);
    expect(bar().className).toContain("bg-destructive");
  });

  it("超出窗口也不画到 100% 以上", () => {
    const { container } = render(<ContextMeter context={{ tokens: 500_000, window: 100_000 }} />);
    expect((container.querySelector("[style*='width']") as HTMLElement).style.width).toBe("100%");
  });

  it("只是读数,不再承载操作 —— 整理入口移进了会话设置", () => {
    const { container } = render(<ContextMeter context={{ tokens: 90, window: 100 }} />);
    // 没有分项时连展开都没有:点开是空的浮层,比不给展开更像坏了。
    expect(container.querySelector("button")).toBeNull();
    expect(container.textContent).toContain("10");
  });

  it("按**实际占用**报剩余,而不是按对话那部分", () => {
    // 工具定义与系统提示每轮重发,一条消息都没有的会话也已经占掉了三成。拿对话量当分子,
    // 水位会在开口前显示"剩余 100%",而它不是 —— 而偏乐观的水位是最坏的那种。
    const { container } = render(
      <ContextMeter
        context={{
          tokens: 0,
          window: 32_000,
          used: 11_535,
          parts: [
            { kind: "messages", tokens: 0 },
            { kind: "tools", tokens: 10_907 },
            { kind: "system", tokens: 628 },
            { kind: "free", tokens: 20_465 },
          ],
        }}
      />,
    );
    expect(container.textContent).toContain("64");
    expect(container.textContent).not.toContain("100");
  });
});

describe("上下文明细", () => {
  const context = {
    tokens: 0,
    window: 32_000,
    used: 11_535,
    parts: [
      { kind: "messages", tokens: 0 },
      { kind: "tools", tokens: 10_907 },
      { kind: "system", tokens: 628 },
      { kind: "free", tokens: 20_465 },
    ],
  };

  it("说清楚窗口被**什么**占的 —— 这里最大的一块不是对话", () => {
    const { container } = render(<ContextBreakdown context={context} />);
    expect(container.textContent).toContain("工具定义");
    expect(container.textContent).toContain("11k");
    // 为 0 的分项不列:一行"对话 0 · 0%"只是噪音。
    expect(container.textContent).not.toContain("对话");
  });

  it("有分项时水位可以点开", () => {
    render(<ContextMeter context={context} />);
    expect(screen.getByRole("button")).toBeTruthy();
  });
});

describe("压缩标记", () => {
  const info = { droppedMessages: 12, tokensBefore: 90_000, tokensAfter: 20_000, summary: "用户要做 1080p 视频。" };

  it("默认折叠,展开后能看到交接说明", () => {
    render(<CompactionNotice info={info} />);
    expect(screen.queryByText(info.summary)).toBeNull();
    fireEvent.click(screen.getByText("expand"));
    expect(screen.getByText(info.summary)).toBeTruthy();
  });

  it("摘要为空时不给展开 —— 点开一片空白比不给展开更像坏了", () => {
    render(<CompactionNotice info={{ ...info, summary: "" }} />);
    expect(screen.queryByText("expand")).toBeNull();
  });
});

describe("分项配色", () => {
  it("只用 tokens.css 里真实存在的变量", () => {
    // 编一个不存在的 CSS 变量不会报错,只会渲染成**透明**。第一版写了 --chart-2/--chart-4,
    // 于是占了 35% 的工具定义那一段在水位条上完全看不见,图例里的色块也是空的 —— 一个
    // "画出来了但看不见"的 bug,没有任何断言会红。所以这一条直接对着令牌文件核。
    const tokens = readFileSync(resolve(__dirname, "../../design/tokens.css"), "utf8");
    const used = Object.values(PART_COLORS).flatMap((cls) => [...cls.matchAll(/var\((--[\w-]+)\)/g)].map((m) => m[1]));

    expect(used.length).toBe(Object.keys(PART_COLORS).length);
    for (const name of used) expect(tokens).toContain(`${name}:`);
  });
});
