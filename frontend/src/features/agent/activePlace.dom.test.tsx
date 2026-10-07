/** @vitest-environment jsdom */

/**
 * 「这个窗口眼下在哪」由页面登记(ADR 0044 §3),智能体带你去别处时递一根接力棒(§6)。
 */

import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { passConversation, resetActivePlaces, useActivePlace, useAgentPlace } from "./activePlace";
import type { AgentPlace } from "./places";
import { readChoice } from "./sessionSelection";

const NOTE: AgentPlace = { kind: "note", id: "n1" };
const OTHER_NOTE: AgentPlace = { kind: "note", id: "n2" };
const COMFY: AgentPlace = { kind: "comfyui", id: "c1/a.json" };
const STUDIO: AgentPlace = { kind: "studio", id: "" };

function Page({ place }: { place: AgentPlace | null }) {
  useAgentPlace(place);
  return null;
}

function Window({ page, workbench }: { page: AgentPlace | null; workbench: AgentPlace | null }) {
  return (
    <>
      {page && <Page place={page} />}
      {workbench && <Page place={workbench} />}
    </>
  );
}

beforeEach(() => {
  resetActivePlaces();
  window.sessionStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe("登记处", () => {
  it("页面 → 工作台盖上去 → 关掉:依次是页面、工作台、页面;都卸了是 AI Studio", () => {
    const active = renderHook(() => useActivePlace());
    const screen = render(<Window page={NOTE} workbench={null} />);
    expect(active.result.current).toEqual(NOTE);
    screen.rerender(<Window page={NOTE} workbench={COMFY} />);
    expect(active.result.current).toEqual(COMFY);
    screen.rerender(<Window page={NOTE} workbench={null} />);
    expect(active.result.current).toEqual(NOTE);
    screen.rerender(<Window page={null} workbench={null} />);
    expect(active.result.current).toEqual(STUDIO);
  });

  it("页面换了地方(换一篇笔记)原地改,盖在上面的工作台还在上面", () => {
    const active = renderHook(() => useActivePlace());
    const screen = render(<Window page={NOTE} workbench={COMFY} />);
    screen.rerender(<Window page={OTHER_NOTE} workbench={COMFY} />);
    expect(active.result.current).toEqual(COMFY);
    screen.rerender(<Window page={OTHER_NOTE} workbench={null} />);
    expect(active.result.current).toEqual(OTHER_NOTE);
  });
});

describe("接力棒", () => {
  it("跳到一样具体的东西上:那一处当场接住这段对话", async () => {
    const screen = render(<Window page={NOTE} workbench={null} />);
    passConversation("w1", "s1");
    await act(async () => screen.rerender(<Window page={OTHER_NOTE} workbench={null} />));
    expect(readChoice("w1", OTHER_NOTE)).toBe("s1");
    expect(readChoice("w1", NOTE)).toBe("");
  });

  it("换页时中间那一下栈是空的:不让 AI Studio 抢走本该是笔记的那根棒子", async () => {
    vi.useFakeTimers();
    const screen = render(<Window page={NOTE} workbench={null} />);
    passConversation("w1", "s1");
    await act(async () => screen.rerender(<Window page={null} workbench={null} />));
    await act(async () => vi.advanceTimersByTime(300));
    await act(async () => screen.rerender(<Window page={OTHER_NOTE} workbench={null} />));
    await act(async () => vi.advanceTimersByTime(5000));
    expect(readChoice("w1", OTHER_NOTE)).toBe("s1");
    expect(readChoice("w1", STUDIO)).toBe("");
  });

  it("跳到没有面板的页面:等一会儿,AI Studio 那一处接住", async () => {
    vi.useFakeTimers();
    const screen = render(<Window page={NOTE} workbench={null} />);
    passConversation("w1", "s1");
    await act(async () => screen.rerender(<Window page={null} workbench={null} />));
    expect(readChoice("w1", STUDIO)).toBe("");
    await act(async () => vi.advanceTimersByTime(2000));
    expect(readChoice("w1", STUDIO)).toBe("s1");
  });

  it("跳到原地(什么都没变):棒子作废,之后自己点开别处不被它接走", async () => {
    vi.useFakeTimers();
    const screen = render(<Window page={NOTE} workbench={null} />);
    passConversation("w1", "s1");
    await act(async () => vi.advanceTimersByTime(2000));
    await act(async () => screen.rerender(<Window page={OTHER_NOTE} workbench={null} />));
    expect(readChoice("w1", OTHER_NOTE)).toBe("");
  });

  it("没有棒子(你自己点过去的):谁都不接", async () => {
    const screen = render(<Window page={NOTE} workbench={null} />);
    await act(async () => screen.rerender(<Window page={OTHER_NOTE} workbench={null} />));
    expect(window.sessionStorage.length).toBe(0);
  });
});
