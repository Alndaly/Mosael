/** @vitest-environment jsdom */
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sparkles } from "lucide-react";

import { FLASH_MS, flashLiveActivity, resetLiveActivities, useLiveActivity, type LiveActivity } from "@/components/island/liveActivities";

const ongoing: LiveActivity = {
  id: "job:1",
  state: "ongoing",
  title: "生成图片",
  detail: "第 3 / 4 张",
  progress: 0.42,
  icon: Sparkles,
};

function Publisher({ activity }: { activity: LiveActivity | null }) {
  useLiveActivity(activity);
  return null;
}

function bridge() {
  const report = vi.fn();
  (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = { platform: "darwin", reportLiveActivities: report };
  return report;
}

beforeEach(() => {
  (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = undefined;
});
afterEach(() => {
  act(() => resetLiveActivities());
  vi.useRealTimers();
});

describe("原生灵动岛的消息格式", () => {
  it("挂着就推,卸下推空;不把图标和回调送过进程边界", () => {
    const report = bridge();
    const { rerender } = render(<Publisher activity={ongoing} />);
    expect(report).toHaveBeenLastCalledWith([{ id: "job:1", state: "ongoing", title: "生成图片", detail: "第 3 / 4 张", progress: 0.42 }]);
    rerender(<Publisher activity={null} />);
    expect(report).toHaveBeenLastCalledWith([]);
  });

  it("做完亮几秒,原生浮层接住就返回 true", () => {
    vi.useFakeTimers();
    const report = bridge();
    expect(flashLiveActivity({ ...ongoing, state: "done", title: "生成图片 · 已完成" })).toBe(true);
    expect(report).toHaveBeenLastCalledWith([{ id: "job:1", state: "done", title: "生成图片 · 已完成", detail: "第 3 / 4 张", progress: 0.42 }]);
    act(() => vi.advanceTimersByTime(FLASH_MS + 10));
    expect(report).toHaveBeenLastCalledWith([]);
  });

  it("没有原生桥时返回 false,调用方可以退回应用内提示", () => {
    expect(flashLiveActivity(ongoing)).toBe(false);
  });

  it("原生回传 open 时按 id 找到发布者", () => {
    bridge();
    const open = vi.fn();
    render(<Publisher activity={{ ...ongoing, onOpen: open }} />);
    act(() => window.dispatchEvent(new CustomEvent("mosael:live-activity-open", { detail: "job:1" })));
    expect(open).toHaveBeenCalledTimes(1);
  });
});
