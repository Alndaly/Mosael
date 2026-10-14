/** @vitest-environment jsdom */

/**
 * 「这个窗口眼下在哪」由页面登记(ADR 0044 §3);换了地方不改任何一处的选择。
 */

import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetActivePlaces, useActivePlace, useAgentPlace } from "./activePlace";
import type { AgentPlace } from "./places";

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

describe("换了地方", () => {
  it("谁的选择都不改:面板显示那一处自己的对话", async () => {
    const screen = render(<Window page={NOTE} workbench={null} />);
    await act(async () => screen.rerender(<Window page={OTHER_NOTE} workbench={null} />));
    expect(window.sessionStorage.length).toBe(0);
  });
});
