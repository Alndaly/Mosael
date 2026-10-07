/** @vitest-environment jsdom */

/**
 * 笔记页说自己在哪(ADR 0044):开着一篇就是那篇笔记,没开就是 AI Studio —— 在页面那一层登记,面板收着也算。
 */

import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const seen = vi.hoisted(() => ({ props: null as null | { AgentPanel?: unknown; onNoteChange?: (id: string | null) => void } }));
vi.mock("@/features/notes/NotesView", () => ({
  NotesView: (props: { AgentPanel?: unknown; onNoteChange?: (id: string | null) => void }) => {
    seen.props = props;
    return null;
  },
}));

import { NotesWithAgent } from "./NotesWithAgent";
import { resetActivePlaces, useActivePlace } from "./activePlace";

beforeEach(() => {
  resetActivePlaces();
  seen.props = null;
});

it("交了助手面板;开着哪篇,眼下就是那篇笔记,没开回到 AI Studio", () => {
  const active = renderHook(() => useActivePlace());
  render(<NotesWithAgent workspace={{ id: "ws" } as never} />);
  expect(seen.props?.AgentPanel).toBeTruthy();
  expect(active.result.current).toEqual({ kind: "studio", id: "" });

  act(() => seen.props?.onNoteChange?.("n1"));
  expect(active.result.current).toEqual({ kind: "note", id: "n1" });
  act(() => seen.props?.onNoteChange?.("n2"));
  expect(active.result.current).toEqual({ kind: "note", id: "n2" });
  act(() => seen.props?.onNoteChange?.(null));
  expect(active.result.current).toEqual({ kind: "studio", id: "" });
});
