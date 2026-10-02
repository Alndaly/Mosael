/** @vitest-environment jsdom */
/**
 * 时间线上的手势:标尺、拖动、修剪落在哪一刻,以及它们在键盘与指针意外中断时的表现。
 *
 * jsdom 没有版面,画布的 getBoundingClientRect 恒为 0,所以指针的 clientX 就是画布里的像素位置:
 * 在默认 40px/s 下,clientX = 41 指的是 1.025 秒。
 */
import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Clip, Sequence, Track } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useEditorStore } from "@/features/editor/editorStore";
import { Timeline } from "@/features/editor/timeline/Timeline";

function clip(id: string, trackId: string, start: number, srcIn: number, srcOut: number, extra: Partial<Clip> = {}): Clip {
  return {
    id, track_id: trackId, asset_id: null, asset_kind: "", timeline_start: start, src_in: srcIn, src_out: srcOut,
    speed: 1, gain: 1, muted: false, text_override: id, effects: {}, transform: {}, ...extra,
  } as Clip;
}

function track(id: string, kind: string, position: number, clips: Clip[] = [], extra: Partial<Track> = {}): Track {
  return { id, kind, name: id, position, muted: false, hidden: false, locked: false, solo: false, duck: false, clips, ...extra } as unknown as Track;
}

type Handlers = Partial<React.ComponentProps<typeof Timeline>>;

function renderTimeline(tracks: Track[], handlers: Handlers = {}, fps = 30) {
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps, tracks } as unknown as Sequence;
  const props = {
    onInsertClip: vi.fn(),
    onMoveClip: vi.fn(),
    onTrimClip: vi.fn(),
    ...handlers,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <DndContext>
          <Timeline sequence={sequence} assets={[]} {...props} />
        </DndContext>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { ...utils, props };
}

beforeEach(() => {
  useEditorStore.setState({ playhead: 0, playing: false, pxPerSecond: 40, selectedClipIds: [], dragDraft: null, tool: "select", editMode: "overwrite" });
});

describe("标尺", () => {
  it("点在两帧之间,播放头吸到最近的那一帧", () => {
    renderTimeline([track("V1", "video", 0)]);
    fireEvent.pointerDown(screen.getByTestId("timeline-ruler"), { clientX: 41, pointerId: 1, buttons: 1 });
    expect(useEditorStore.getState().playhead).toBe(31 / 30);
    expect(screen.getByTestId("timeline-playhead-readout").textContent).toMatch(/^00:00:01:01/);
  });
});

describe("修剪", () => {
  it("尾边落在帧上(按序列帧率)", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 4)])], {}, 25);
    const handle = screen.getByTestId("trim-end-c1");
    fireEvent.pointerDown(handle, { clientX: 160, pointerId: 1, button: 0, buttons: 1 });
    // 81px = 2.025s,25fps 下最近的帧是第 51 帧(2.04s)。
    fireEvent.pointerMove(handle, { clientX: 81, pointerId: 1, buttons: 1 });
    fireEvent.pointerUp(handle, { clientX: 81, pointerId: 1 });
    expect(props.onTrimClip).toHaveBeenCalledWith("c1", { timeline_start: 0, src_in: 0, src_out: 51 / 25 });
  });
});

describe("拖动", () => {
  it("落点吸到帧上", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2)])]);
    const body = screen.getByTestId("clip-c1");
    act(() => {
      fireEvent.pointerDown(body, { clientX: 10, pointerId: 1, button: 0, buttons: 1 });
    });
    // 位移 51px = 1.275s → 第 38.25 帧 → 第 38 帧。
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 61, clientY: 0, buttons: 1 }));
      window.dispatchEvent(new MouseEvent("pointerup", { clientX: 61, clientY: 0 }));
    });
    expect(props.onMoveClip).toHaveBeenCalledWith("c1", 38 / 30, undefined, false);
  });
});

describe("复制与剪切的标记", () => {
  it("文字 / 字幕片段也能复制:工具栏的复制键可用,点了交给 onDuplicateClip", () => {
    const onDuplicateClip = vi.fn();
    renderTimeline([track("S1", "subtitle", 0, [clip("c1", "S1", 0, 0, 2)])], { onDuplicateClip });
    act(() => useEditorStore.getState().selectClip("c1"));
    const button = screen.getByRole("button", { name: "duplicateClip" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onDuplicateClip).toHaveBeenCalledWith("c1");
  });

  it("剪切了还没粘贴的片段在时间线上标出来", () => {
    renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2), clip("c2", "V1", 3, 0, 1)])]);
    act(() => useEditorStore.getState().setClipboard({ clipIds: ["c1"], cut: true }));
    expect(screen.getByTestId("clip-c1")).toHaveAttribute("data-cut", "true");
    expect(screen.getByTestId("clip-c2")).not.toHaveAttribute("data-cut");
  });
});
