/** @vitest-environment jsdom */
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

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { CompactionNotice, ContextMeter } from "@/components/agent/ContextMeter";

describe("上下文水位", () => {
  it("窗口未知时整条不渲染", () => {
    const { container } = render(<ContextMeter context={{ tokens: 5000, window: 0 }} />);
    expect(container.textContent).toBe("");
    expect(render(<ContextMeter context={null} />).container.textContent).toBe("");
  });

  it("按窗口给出比例,并在过线时转成告警色", () => {
    const { container, rerender } = render(<ContextMeter context={{ tokens: 20_000, window: 100_000 }} />);
    const bar = () => container.querySelector("[style*='width']") as HTMLElement;
    expect(bar().style.width).toBe("20%");
    expect(bar().className).toContain("bg-primary");

    // 80% 是 sidecar 的触发阈值,到这条线就该显眼。
    rerender(<ContextMeter context={{ tokens: 85_000, window: 100_000 }} />);
    expect(bar().className).toContain("bg-destructive");
  });

  it("超出窗口也不画到 100% 以上", () => {
    const { container } = render(<ContextMeter context={{ tokens: 500_000, window: 100_000 }} />);
    expect((container.querySelector("[style*='width']") as HTMLElement).style.width).toBe("100%");
  });

  it("运行中不给整理入口 —— 半路换掉上下文会把正在跑的这一轮弄乱", () => {
    const { container } = render(<ContextMeter context={{ tokens: 10, window: 100 }} />);
    expect(container.querySelector("button")).toBeNull();
    const onCompact = vi.fn();
    render(<ContextMeter context={{ tokens: 10, window: 100 }} onCompact={onCompact} />);
    fireEvent.click(screen.getByLabelText("agentCompactNow"));
    expect(onCompact).toHaveBeenCalledOnce();
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
