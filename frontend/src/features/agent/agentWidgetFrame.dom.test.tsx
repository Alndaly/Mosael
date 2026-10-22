/** @vitest-environment jsdom */
/**
 * 智能体小界面画进一轮回答的结果区:框的属性就是安全边界的落地(只给 allow-scripts、不带 referrer、
 * 文档开头是 CSP),复制拿到的是模型原样的源码,展开时对话里那一份先卸下。
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** 以「这个框的窗口」身份报一个高度上来。 */
function reportHeight(frame: HTMLIFrameElement, height: number) {
  window.dispatchEvent(
    new MessageEvent("message", { data: { type: "mosael-widget-height", height }, source: frame.contentWindow }),
  );
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

  it("回答落定重挂后,高度从上次谈好的接着来 —— 视口相对的内容不会重新回环缩水", async () => {
    const first = render(<AgentWidgetFrame widget={widget} />);
    reportHeight(frames()[0], 400);
    await waitFor(() => expect(frames()[0].style.height).toBe("400px"));
    first.unmount();

    // 同一颗组件(实时流 → 落库消息)重挂:不从初始档位重来,直接站在 400。
    render(<AgentWidgetFrame widget={widget} />);
    expect(frames()[0].style.height).toBe("400px");
  });

  it("单次上报缩到六成以下按回环拒收 —— 内容跟着框高走的一圈比一圈矮不是「变矮」", async () => {
    render(<AgentWidgetFrame widget={widget} />);
    reportHeight(frames()[0], 500);
    await waitFor(() => expect(frames()[0].style.height).toBe("500px"));
    // 拒收不需要真等:更新被拦下,flush 之后值根本不会变。
    await act(async () => {
      reportHeight(frames()[0], 120);
    });
    expect(frames()[0].style.height).toBe("500px");
    // 分步的真变矮照常收:500 → 350 是七成,过。
    reportHeight(frames()[0], 350);
    await waitFor(() => expect(frames()[0].style.height).toBe("350px"));
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
    //: 焦点不能落进框:落进去 Esc 就按在框里的文档上,弹窗关不掉。
    expect(frames()[0].tabIndex).toBe(-1);
    expect(document.activeElement?.tagName).not.toBe("IFRAME");
  });

  it("没标题时用通用名", () => {
    render(<AgentWidgetFrame widget={{ ...widget, title: "" }} />);
    expect(frames()[0].getAttribute("title")).toBe("agentWidgetUntitled");
  });
});

describe("小界面画在答案里(智能体主动要展示的东西)", () => {
  const timeline: AgentTimelineItem[] = [
    { type: "tool", tool: { id: "s1", name: "show_widget", status: "done", args: widget, result: { shown: true, title: widget.title } } },
    { type: "tool", tool: { id: "s2", name: "show_widget", status: "error", args: { title: "坏的", html: "<p>x</p>" }, result: { error: "too long" } } },
    { type: "text", text: "地图在上面" },
  ];

  it("成功的那次画在答案里,失败的不画;过程里不再摆第二份", async () => {
    render(<AgentTurnContent timeline={timeline} />);
    const result = document.querySelector("[data-turn-result]");
    //: show_widget 的契约就是「把这个拿给用户看」—— 它属于答案,不埋在折叠的「已处理」里。
    await waitFor(() => expect(result?.querySelector('[data-agent-widget="s1"]')).not.toBeNull());
    expect(result?.textContent).toContain("地图在上面");
    expect(document.querySelector('[data-agent-widget="s2"]')).toBeNull();

    // 过程摊开之后也没有第二份。
    fireEvent.click(screen.getByRole("button", { name: /agentProcessDone/ }));
    const row = document.querySelector<HTMLElement>("[data-tool-call='s1']");
    expect(row?.querySelector("[data-agent-widget]")).toBeNull();
  });
});
