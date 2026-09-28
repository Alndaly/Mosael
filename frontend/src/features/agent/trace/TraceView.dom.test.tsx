/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

/**
 * 轨迹视图的空白状态分三种,和对话视图同一条规矩:「还没读到」「正在跑、还没有步骤」
 * 都不能说成「这条会话是空的」。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TraceView } from "@/features/agent/trace/TraceView";

it("读取中显示加载,不显示空态", () => {
  render(<TraceView messages={[]} streamTimeline={[]} usageEvents={[]} loading />);
  expect(screen.getByText("chatLoadingSession")).toBeTruthy();
  expect(screen.queryByText("traceEmptyTitle")).toBeNull();
});

it("正在跑、还没有步骤时显示运行状态,不显示空态", () => {
  render(<TraceView messages={[]} streamTimeline={[]} usageEvents={[]} runningLabel="运行中 · 3s" />);
  expect(screen.getByText("运行中 · 3s")).toBeTruthy();
  expect(screen.queryByText("traceEmptyTitle")).toBeNull();
});

it("读完了、没在跑、也没有步骤,才是空态", () => {
  render(<TraceView messages={[]} streamTimeline={[]} usageEvents={[]} />);
  expect(screen.getByText("traceEmptyTitle")).toBeTruthy();
});
