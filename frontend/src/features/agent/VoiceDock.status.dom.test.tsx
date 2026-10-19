/** @vitest-environment jsdom */

/**
 * 免提浮标在**生成语音**这一段要有明确的状态,不能只剩一颗点点点。
 *
 * 维护者原话:「智能体助手在音频生成过程中没有 loading 以及对应 UI —— 生成语音时没有任何状态变化」。
 * 语音是没有界面的交互:从「它答完了」到「声音出来」之间有一段真实的等待(合成一次要一两秒,
 * 远端引擎还要多一次往返),而此前这一段和「在说」共用同一个状态 —— 屏幕上看起来什么都没发生。
 *
 * 这里的几条守的是同一个东西的两面:
 * - 生成中有**转圈**(环形进度)和**一句可见的状态文字**(中英各一条);
 * - 失败**说清原因、并且点一下就能重试** —— 语音模式下静默失败会被理解成「它没听见」;
 * - 浮着的浮标和收进外壳顶栏的那一颗是**同一个状态机 + 同一套组件**,说法一句不差。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  state: "synthesizing" as string,
  speechFailure: null as null | { message: string; retryable: boolean },
  retrySpeech: vi.fn(),
  stop: vi.fn(),
  start: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  listAgentSessions: async () => [],
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentMessages: async () => [],
  sendAgentMessage: vi.fn(),
  isNotFound: () => false,
}));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] };
});
vi.mock("@/components/app/useFloatingPanel", () => ({
  useFloatingPanel: () => ({ style: {}, startDrag: () => {}, wasDragged: () => false, focusProps: {} }),
}));
vi.mock("@/features/agent/useVoiceLoop", () => ({
  useVoiceLoop: () => ({
    on: true,
    state: h.state,
    heard: "",
    levelRef: { current: 0 },
    start: h.start,
    stop: h.stop,
    speechFailure: h.speechFailure,
    retrySpeech: h.retrySpeech,
  }),
}));

import { messages } from "@/app/messages";
import { ChromeStatusSlot } from "@/components/app/chromeStatusSlot";
import { APP_CHROME } from "@/components/ui/appChrome";
import { resetNativeViewForTests } from "@/lib/nativeView";
import { VoiceDock } from "./VoiceDock";

const T = messages["zh-CN"];

let push: ((state: { visible: boolean }) => void) | null = null;

function mountFloating() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

function mountInChrome() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <div {...APP_CHROME} data-testid="bar">
        <ChromeStatusSlot size="xs" />
      </div>
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

function caption(): HTMLElement {
  return document.querySelector("[data-voice-caption]") as HTMLElement;
}

beforeEach(() => {
  h.state = "synthesizing";
  h.speechFailure = null;
  h.retrySpeech.mockReset();
  h.stop.mockReset();
  h.start.mockReset();
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

it("正在生成语音:环上有转圈,旁边一句看得见的状态文字", () => {
  mountFloating();

  const orb = document.querySelector('[data-voice-state="synthesizing"]');
  expect(orb, "浮标没有「生成语音中」这个状态").toBeTruthy();
  expect(orb?.querySelector("[data-voice-generating]"), "生成语音时没有转圈/进度环").toBeTruthy();

  expect(caption(), "生成语音时没有状态说明").toBeTruthy();
  expect(caption().textContent).toBe(T.voiceMode_synthesizing);
  expect(caption().className).toMatch(/\bopacity-100\b/);
});

it("合成失败:说清原因,并且点一下浮标就重试 —— 不是静默,也不是只能关掉", () => {
  h.state = "synthesisFailed";
  h.speechFailure = { message: "连不上配音服务", retryable: true };
  mountFloating();

  expect(caption().textContent).toContain(T.voiceMode_synthesisFailed);
  expect(caption().textContent).toContain("连不上配音服务");
  expect(caption().textContent).toContain(T.voiceDockRetry);
  expect(document.querySelector('[data-voice-state="synthesisFailed"]')).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: T.voiceMode_synthesisFailed }));
  expect(h.retrySpeech).toHaveBeenCalledOnce();
  expect(h.stop, "点一下失败中的浮标不该是把免提关掉").not.toHaveBeenCalled();
});

it("换到外壳顶栏里也是同一句话:两处用的是同一个状态机,不是两套说法", () => {
  mountInChrome();
  expect(screen.queryByRole("complementary")).toBeNull();
  const icon = screen.getByRole("button", { name: T.voiceMode_synthesizing });
  expect(screen.getByTestId("bar").contains(icon)).toBe(true);
  expect(icon.getAttribute("aria-label")).toBe(T.voiceMode_synthesizing);
});

it("收进顶栏后失败也在:读得出原因,点它同样是重试", () => {
  h.state = "synthesisFailed";
  h.speechFailure = { message: "连不上配音服务", retryable: true };
  mountInChrome();

  const icon = screen.getByRole("button", { name: T.voiceMode_synthesisFailed });
  fireEvent.click(icon);
  expect(h.retrySpeech).toHaveBeenCalledOnce();
  expect(h.stop).not.toHaveBeenCalled();
});

it("视图收起再回来:同一套状态、同一句话(不因为换了个地方画就丢掉生成中)", () => {
  mountInChrome();
  //: 顶栏那一颗的读屏名。
  const inChrome = screen.getByRole("button", { name: T.voiceMode_synthesizing }).getAttribute("aria-label");
  act(() => push?.({ visible: false }));
  expect(screen.getByRole("complementary")).toBeTruthy();
  //: 浮着的那一颗旁边那一行。**两处必须是同一句话** —— 否则就是"每处各写一套"。
  expect(caption().textContent).toBe(inChrome);
});
