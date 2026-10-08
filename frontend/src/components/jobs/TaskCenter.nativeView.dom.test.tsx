/** @vitest-environment jsdom */
/**
 * 点系统通知「需要登录」「需要你处理」进来(ADR 0051 D34):内嵌浏览器、工作台的画布在前台时,任务中心在它们前面打开 ——
 * 抬过外壳、请原生视图让开;收起时视图回来。真机上它曾整块画在网页底下:窗口被唤到前台,人看不出任何变化,按「返回 Mosael」
 * 之后还开着一个不记得自己开过的任务中心。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));
vi.mock("@/api/client", () => ({
  api: async () => [],
  fetchJobKinds: async () => ({ kinds: [], fallback: { kind: "", label: "任务", announce: "always", affects: [], view: null, record_field: null } }),
  getJob: vi.fn(),
  clearTaskCenter: vi.fn(),
  taskCenterQuery: (workspaceId: string) => ({
    queryKey: ["jobs", workspaceId, "task-center", "shown"],
    queryFn: async () => ({ jobs: [], cleared_at: null }),
  }),
}));

import { OverNativeView } from "@/components/app/overNativeView";
import { resetNativeViewAside, settleNativeViewAside } from "@/components/ui/nativeViewAside";
import { TooltipProvider } from "@/components/ui/tooltip";
import { resetNativeViewForTests } from "@/lib/nativeView";
import { TaskCenter } from "./TaskCenter";

function desktop(visible: boolean) {
  const setOverlay = vi.fn(async (_up: boolean) => undefined);
  vi.stubGlobal("mosaelPublish", {
    onViewState: (callback: (state: { visible: boolean }) => void) => {
      callback({ visible });
      return () => undefined;
    },
    setOverlay,
  });
  resetNativeViewForTests();
  return setOverlay;
}

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <OverNativeView>
          <TaskCenter workspaceId="w1" />
        </OverNativeView>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  act(() => void window.dispatchEvent(new CustomEvent("mosael:open-tasks")));
}

afterEach(async () => {
  cleanup();
  await settleNativeViewAside();
  resetNativeViewAside();
  vi.unstubAllGlobals();
  resetNativeViewForTests();
});

describe("系统通知点进来时,任务中心在原生视图前面打开", () => {
  it("视图在前台:弹出层抬过外壳(z 210、算外壳),开着时视图让开;按 Esc 收起,视图回来", async () => {
    const setOverlay = desktop(true);
    mount();
    const panel = await screen.findByRole("dialog", { name: "taskCenter" });
    expect(panel.hasAttribute("data-over-chrome")).toBe(true);
    expect(panel.hasAttribute("data-app-chrome")).toBe(true);
    await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true]]));
    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true], [false]]));
  });

  it("视图不在前台:和平时一样,不抬层、不请视图让开", async () => {
    const setOverlay = desktop(false);
    mount();
    const panel = await screen.findByRole("dialog", { name: "taskCenter" });
    expect(panel.hasAttribute("data-over-chrome")).toBe(false);
    //: 没有拍画面这一步时,请视图让开是在弹出层挂上的那一刻同步发出去的:此刻没发就是没发
    expect(setOverlay).not.toHaveBeenCalled();
  });
});
