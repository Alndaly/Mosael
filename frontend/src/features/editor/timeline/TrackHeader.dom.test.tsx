/** @vitest-environment jsdom */
/**
 * 轨道头上的独奏(S)/ 闪避(D)。
 *
 * 用户问「S 和 D 是干什么的,点了没反应」。这里钉三件事:它们说得出自己是什么(可读的名字 +
 * 悬停说明)、按下去的状态看得见(aria-pressed),以及字幕轨头上**没有**这两个 —— 字幕轨没有
 * 声音,独奏它反而让整片静音。
 */
import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Sequence, Track } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Timeline } from "@/features/editor/timeline/Timeline";

function track(id: string, kind: Track["kind"], state: Partial<Track> = {}): Track {
  return { id, kind, name: id, position: 0, muted: false, locked: false, solo: false, duck: false, clips: [], ...state } as Track;
}

function renderTimeline(tracks: Track[], onSetTrackState = vi.fn()) {
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps: 30, tracks } as unknown as Sequence;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <DndContext>
          <Timeline
            sequence={sequence}
            assets={[]}
            onInsertClip={vi.fn()}
            onMoveClip={vi.fn()}
            onTrimClip={vi.fn()}
            onSetTrackState={onSetTrackState}
          />
        </DndContext>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return onSetTrackState;
}

/** 一条轨的轨道头:从轨名往上找到那一行。 */
function header(name: string): HTMLElement {
  return screen.getByText(name).closest(".group\\/label") as HTMLElement;
}

describe("轨道头的独奏 / 闪避", () => {
  it("音频轨和视频轨上有 S 和 D,名字说得出自己是什么,点下去改的是这条轨", async () => {
    const onSet = renderTimeline([track("V1", "video"), track("A1", "audio")]);
    for (const name of ["V1", "A1"]) {
      const row = within(header(name));
      expect(row.getByRole("button", { name: "trackSolo" })).toHaveAttribute("aria-pressed", "false");
      expect(row.getByRole("button", { name: "trackDuck" })).toHaveAttribute("aria-pressed", "false");
    }
    await userEvent.click(within(header("A1")).getByRole("button", { name: "trackDuck" }));
    expect(onSet).toHaveBeenCalledWith("A1", { duck: true });
    await userEvent.click(within(header("V1")).getByRole("button", { name: "trackSolo" }));
    expect(onSet).toHaveBeenCalledWith("V1", { solo: true });
  });

  it("按下去的状态一直看得见,再点一次是取消", async () => {
    const onSet = renderTimeline([track("A1", "audio", { solo: true, duck: true })]);
    const row = within(header("A1"));
    const solo = row.getByRole("button", { name: "trackUnsolo" });
    const duck = row.getByRole("button", { name: "trackUnduck" });
    expect(solo).toHaveAttribute("aria-pressed", "true");
    expect(duck).toHaveAttribute("aria-pressed", "true");
    // 平时轨道头的开关是藏着的(移上去才露出来);按下去的不藏。
    expect(solo.className).toMatch(/(^|\s)opacity-100(\s|$)/);
    expect(duck.className).toMatch(/(^|\s)opacity-100(\s|$)/);
    await userEvent.click(solo);
    expect(onSet).toHaveBeenCalledWith("A1", { solo: false });
  });

  it("悬停说明这个开关按下去之后会怎样", async () => {
    renderTimeline([track("A1", "audio")]);
    await userEvent.hover(within(header("A1")).getByRole("button", { name: "trackDuck" }));
    expect((await screen.findAllByText("trackDuckHint")).length).toBeGreaterThan(0);
  });

  it("字幕轨没有声音,头上没有 S 和 D;静音(隐藏)和锁定还在", () => {
    renderTimeline([track("S1", "subtitle")]);
    const row = within(header("S1"));
    expect(row.queryByRole("button", { name: "trackSolo" })).toBeNull();
    expect(row.queryByRole("button", { name: "trackDuck" })).toBeNull();
    expect(row.getByRole("button", { name: "trackMute" })).toBeInTheDocument();
    expect(row.getByRole("button", { name: "trackLock" })).toBeInTheDocument();
  });
});
