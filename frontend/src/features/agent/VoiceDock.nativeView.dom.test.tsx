/** @vitest-environment jsdom */

/**
 * 免提浮标在内嵌浏览器、工作台的画布前台时收成外壳顶栏上的一个图标(ADR 0051 D37):浮标拖到哪儿都可能落在网页底下,看不见、
 * 点不着。收进去的是同一个免提循环 —— 说话照常,不因为换了个地方画就断掉重来;视图收起,回到原来拖到的位置。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), mounts: 0 }));
vi.mock("@/api/client", () => ({
  listAgentSessions: async () => [],
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentMessages: async () => [],
  sendAgentMessage: vi.fn(),
  isNotFound: () => false,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/agent/VoiceOrb", () => ({ VoiceOrb: () => null }));
vi.mock("@/components/app/useFloatingPanel", () => ({
  useFloatingPanel: () => ({ style: { left: 700, top: 500 }, startDrag: () => {}, wasDragged: () => false, focusProps: {} }),
}));
vi.mock("@/features/agent/useVoiceLoop", async () => {
  const { useEffect } = await import("react");
  return {
    useVoiceLoop: () => {
      useEffect(() => {
        h.mounts += 1;
      }, []);
      return { on: false, state: "off", heard: "", levelRef: { current: 0 }, start: h.start, stop: h.stop };
    },
  };
});

import { ChromeStatusSlot } from "@/components/app/chromeStatusSlot";
import { APP_CHROME } from "@/components/ui/appChrome";
import { resetNativeViewForTests } from "@/lib/nativeView";
import { VoiceDock } from "./VoiceDock";

let push: ((state: { visible: boolean }) => void) | null = null;

beforeEach(() => {
  h.start.mockReset();
  h.mounts = 0;
  vi.stubGlobal("mosaelPublish", {
    onViewState: (callback: (state: { visible: boolean }) => void) => {
      push = callback;
      callback({ visible: true });
      return () => (push = null);
    },
  });
  resetNativeViewForTests();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetNativeViewForTests();
});

function mount(size: "xs" | "sm") {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <div {...APP_CHROME} data-testid="bar">
        <ChromeStatusSlot size={size} />
      </div>
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

it("视图在前台:浮标收成外壳顶栏上的一个图标(和顶栏的控件同一档),点它照常开始说话", () => {
  mount("xs");
  expect(screen.queryByRole("complementary")).toBeNull();
  const icon = screen.getByRole("button", { name: "voiceModeStart" });
  expect(screen.getByTestId("bar").contains(icon)).toBe(true);
  expect(icon.className).toMatch(/\bsize-7\b/);
  fireEvent.click(icon);
  expect(h.start).toHaveBeenCalledTimes(1);
});

it("工作台的顶栏是 sm 那一档", () => {
  mount("sm");
  expect(screen.getByRole("button", { name: "voiceModeStart" }).className).toMatch(/\bsize-8\b/);
});

it("视图收起:回到浮着的那一颗;同一个免提循环,不断掉重来", () => {
  mount("xs");
  act(() => push?.({ visible: false }));
  expect(screen.getByRole("complementary")).toBeTruthy();
  expect(screen.getByTestId("bar").querySelector("button")).toBeNull();
  act(() => push?.({ visible: true }));
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(h.mounts).toBe(1);
});
