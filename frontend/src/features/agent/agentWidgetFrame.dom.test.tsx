/** @vitest-environment jsdom */
/**
 * 智能体小界面画进一轮回答的结果区:框的属性就是安全边界的落地(只给 allow-scripts、不带 referrer、
 * 文档开头是 CSP),复制拿到的是模型原样的源码,展开时对话里那一份先卸下。
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => <div>{children}</div>,
  CodeBlockCopyButton: () => <button type="button" />,
}));

import { AgentWidgetFrame } from "@/features/agent/AgentWidgetFrame";
import { WIDGET_CSP } from "@/features/agent/agentWidget";
import { AgentTurnContent, type AgentTimelineItem } from "@/features/agent/ToolCalls";

afterEach(cleanup);

const widget = { id: "w1", title: "杭州的三个点", html: '<div id="map"></div><script>draw()</script>' };

function frames(): HTMLIFrameElement[] {
  return Array.from(document.querySelectorAll<HTMLIFrameElement>("iframe[data-agent-widget-frame]"));
}

describe("AgentWidgetFrame", () => {
  it("框只给 allow-scripts、不带 referrer、不写 allow;文档开头是我们的 CSP", () => {
    render(<AgentWidgetFrame widget={widget} />);
    const [frame] = frames();
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.hasAttribute("allow")).toBe(false);
    expect(frame.getAttribute("title")).toBe("杭州的三个点");
    const srcDoc = frame.getAttribute("srcdoc") ?? "";
    expect(srcDoc.indexOf(WIDGET_CSP)).toBeGreaterThan(-1);
    expect(srcDoc.indexOf(WIDGET_CSP)).toBeLessThan(srcDoc.indexOf(widget.html));
  });

  it("别的窗口发来的高度消息不改框高", () => {
    render(<AgentWidgetFrame widget={widget} />);
    const [frame] = frames();
    const before = frame.style.height;
    window.dispatchEvent(new MessageEvent("message", { data: { type: "mosael-widget-height", height: 500 }, source: window }));
    expect(frame.style.height).toBe(before);
  });

  it("复制拿到模型原样的源码", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<AgentWidgetFrame widget={widget} />);
    fireEvent.click(screen.getByRole("button", { name: "agentWidgetCopySource" }));
    expect(writeText).toHaveBeenCalledWith(widget.html);
    await waitFor(() => expect(screen.getByRole("button", { name: "copied" })).toBeTruthy());
  });

  it("展开:全屏里一份,对话里那一份卸下 —— 同一时刻只跑一份脚本", async () => {
    render(<AgentWidgetFrame widget={widget} />);
    fireEvent.click(screen.getByRole("button", { name: "agentWidgetExpand" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(frames()).toHaveLength(1);
    expect(screen.getByRole("dialog").contains(frames()[0])).toBe(true);
  });

  it("没标题时用通用名", () => {
    render(<AgentWidgetFrame widget={{ ...widget, title: "" }} />);
    expect(frames()[0].getAttribute("title")).toBe("agentWidgetUntitled");
  });
});

describe("小界面进一轮回答的结果区", () => {
  const timeline: AgentTimelineItem[] = [
    { type: "tool", tool: { id: "s1", name: "show_widget", status: "done", args: widget, result: { shown: true, title: widget.title } } },
    { type: "tool", tool: { id: "s2", name: "show_widget", status: "error", args: { title: "坏的", html: "<p>x</p>" }, result: { error: "too long" } } },
    { type: "text", text: "地图在上面" },
  ];

  it("成功的那次画在结果里(过程收起也看得见),失败的不画", () => {
    render(<AgentTurnContent timeline={timeline} />);
    const result = document.querySelector("[data-turn-result]");
    expect(result?.querySelector('[data-agent-widget="s1"]')).not.toBeNull();
    expect(document.querySelector('[data-agent-widget="s2"]')).toBeNull();
    expect(document.querySelector("[data-turn-process]")).toBeNull();
  });
});
