/** @vitest-environment jsdom */
/**
 * 时间线的性能棘轮:几千段的时间线,拖一下、点一下、缩放一下,不能再整树协调。
 *
 * 修之前(同一台机器、jsdom、3000 段):拖动每步 ~270ms、点选 ~210ms、缩放 ~445ms,DOM 节点 18878、
 * 刻度 3020 根(1 小时 240px/s 是 28801 根)。原因是每段都渲染、每段带现捏的闭包和自己的一棵右键菜单、
 * 刻度从 0 画到尾。
 *
 * 断言分两类:**数量**(只画视口里的片段和刻度)是确定的,收得紧;**耗时**受机器和并行影响,阈值放得
 * 很宽 —— 只为抓住「又退回整树渲染」那种数量级的回退,不为卡毫秒。
 */
import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));

import type { Sequence, Track } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Timeline } from "@/features/editor/timeline/Timeline";
import { useEditorStore } from "@/features/editor/editorStore";

function build(nClips: number, nTracks = 4, spacing = 2): Sequence {
  const tracks: Track[] = [];
  const per = Math.ceil(nClips / nTracks);
  for (let t = 0; t < nTracks; t++) {
    const clips = [];
    for (let i = 0; i < per; i++) {
      clips.push({
        id: `c${t}_${i}`, track_id: `t${t}`, asset_id: null, text_override: `clip ${i}`,
        timeline_start: i * spacing, src_in: 0, src_out: spacing * 0.9, speed: 1, effects: {}, transform: {},
      });
    }
    tracks.push({
      id: `t${t}`, kind: t === nTracks - 1 ? "subtitle" : "video", name: `T${t}`, position: t,
      muted: false, hidden: false, locked: false, solo: false, duck: false, clips,
    } as unknown as Track);
  }
  return { id: "s", name: "S", width: 1920, height: 1080, fps: 30, tracks } as unknown as Sequence;
}

function mount(sequence: Sequence) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <DndContext>
          <Timeline
            sequence={sequence}
            assets={[]}
            onInsertClip={vi.fn()}
            onMoveClip={vi.fn()}
            onTrimClip={vi.fn()}
            onDeleteClips={vi.fn()}
            onRippleDeleteClips={vi.fn()}
            onSplitClip={vi.fn()}
          />
        </DndContext>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const time = (fn: () => void) => {
  const start = performance.now();
  act(fn);
  return performance.now() - start;
};
/** 多量几次取中位数:整套并行跑时单次测量会被别的 worker 抢走 CPU,中位数不怕偶发的一次慢。 */
const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
const renderedClips = (root: HTMLElement) => root.querySelectorAll("[data-clip-id]").length;
const rulerTicks = (root: HTMLElement) => root.querySelectorAll(".bg-\\[var\\(--ruler-tick\\)\\]").length;

afterEach(() => useEditorStore.setState({ dragDraft: null, selectedClipIds: [], pxPerSecond: 40, playhead: 0 }));

describe("时间线虚拟化", () => {
  it("3000 段:只画视口里的片段,拖动 / 点选 / 缩放不再整树协调", () => {
    useEditorStore.setState({ pxPerSecond: 40, dragDraft: null, selectedClipIds: [], playhead: 0 });
    const { container, unmount } = mount(build(3000));
    // 视口(jsdom 量不到,按兜底宽度)+ 两侧缓冲:四条轨各几十段,而不是 3000。
    expect(renderedClips(container)).toBeLessThan(400);

    const drags: number[] = [];
    for (let i = 0; i < 20; i++) {
      drags.push(
        time(() =>
          useEditorStore.getState().setDragDraft({
            clipId: "c0_0", trackId: "t0", timeline_start: 0.1 * i, src_in: 0, src_out: 1.8, kind: "move",
          }),
        ),
      );
    }
    const drag = median(drags);
    act(() => useEditorStore.getState().setDragDraft(null));
    const select = median([0, 1, 2, 3, 4].map((i) => time(() => useEditorStore.getState().selectClip(`c1_${i}`))));
    const zoom = median([80, 40, 80, 40, 80].map((px) => time(() => useEditorStore.getState().setPxPerSecond(px))));
    expect(renderedClips(container)).toBeLessThan(400);

    // 修之前(单机,jsdom):拖动 ~280、点选 ~260、缩放 ~310ms;修之后 3 / 2 / 8ms。阈值只抓数量级回退。
    expect(drag).toBeLessThan(80);
    expect(select).toBeLessThan(80);
    expect(zoom).toBeLessThan(150);
    unmount();
  }, 60_000);

  it("拖动中正在拖的那段一直在 DOM 里,哪怕它被拖出了视口", () => {
    useEditorStore.setState({ pxPerSecond: 40, dragDraft: null, selectedClipIds: [], playhead: 0 });
    const { container, unmount } = mount(build(400));
    act(() =>
      useEditorStore.getState().setDragDraft({
        clipId: "c0_0", trackId: "t0", timeline_start: 700, src_in: 0, src_out: 1.8, kind: "move",
      }),
    );
    expect(container.querySelector('[data-clip-id="c0_0"]')).not.toBeNull();
    // 视口外的普通片段不画。
    expect(container.querySelector('[data-clip-id="c0_90"]')).toBeNull();
    unmount();
  });

  it("1 小时 240px/s:标尺只画视口里的刻度(此前 28801 根)", () => {
    useEditorStore.setState({ pxPerSecond: 240, dragDraft: null, selectedClipIds: [], playhead: 0 });
    const { container, unmount } = mount(build(2, 1, 3600));
    expect(rulerTicks(container)).toBeGreaterThan(0);
    expect(rulerTicks(container)).toBeLessThan(400);
    unmount();
  });
});
