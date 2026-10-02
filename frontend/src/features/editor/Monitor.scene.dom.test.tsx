/** @vitest-environment jsdom */
/**
 * 监视器:画什么(交给合成器的图层)、播放头怎么走。
 *
 * 合成器本身(WebCodecs 解码 + canvas)在 jsdom 里跑不了,换成记录收到哪些图层的桩;被测的是
 * Monitor 自己的判定 —— 哪段是底图、哪段是叠加、按什么顺序 —— 以及走帧/时间码。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

type SeenLayer = { clip: { id: string }; isBase?: boolean; transformOverride?: unknown };
const seen = vi.hoisted(() => ({
  layers: [] as SeenLayer[],
  overlay: null as null | { onChange: (tf: unknown) => void; onCommit: (tf: unknown) => void },
}));

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/editor/playback/CanvasCompositor", () => ({
  CanvasCompositor: ({ layers }: { layers: SeenLayer[] }) => {
    seen.layers = layers;
    return <canvas data-testid="compositor" />;
  },
}));
vi.mock("@/features/editor/playback/WebAudioMixer", () => ({ WebAudioMixer: () => null }));
vi.mock("@/features/editor/TransformOverlay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/editor/TransformOverlay")>()),
  TransformOverlay: (props: { onChange: (tf: unknown) => void; onCommit: (tf: unknown) => void }) => {
    seen.overlay = props;
    return null;
  },
}));
vi.mock("@/features/editor/playback/compositorFlag", () => ({ compositorSupported: () => true }));

import type { Asset, Clip, Sequence, Track } from "@/api/client";
import { Monitor } from "@/features/editor/Monitor";
import { useEditorStore } from "@/features/editor/editorStore";

function clip(id: string, trackId: string, start: number, end: number, extra: Partial<Clip> = {}): Clip {
  return {
    id, track_id: trackId, asset_id: "img", asset_kind: "image", timeline_start: start, src_in: 0, src_out: end - start,
    speed: 1, gain: 1, muted: false, text_override: null, effects: {}, transform: {}, ...extra,
  } as Clip;
}

function track(id: string, position: number, clips: Clip[], kind = "video"): Track {
  return { id, kind, name: id, position, muted: false, hidden: false, locked: false, solo: false, duck: false, clips } as unknown as Track;
}

const assets = [{ id: "img", kind: "image", name: "still", media_info: {} }] as unknown as Asset[];

function renderMonitor(tracks: Track[], fps = 30, props: Partial<React.ComponentProps<typeof Monitor>> = {}) {
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps, tracks, reframe: {}, subtitle_style: {} } as unknown as Sequence;
  return render(<Monitor sequence={sequence} assets={assets} {...props} />);
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  seen.layers = [];
  seen.overlay = null;
  useEditorStore.setState({ playhead: 0, playing: false, selectedClipIds: [] });
});

/** 监视器交给合成器的图层,写成契约语料的形状:哪段、是不是底图。 */
function layerSummary() {
  return seen.layers.map((layer) => ({ clip: layer.clip.id, isBase: layer.isBase }));
}

describe("监视器画哪些层(与导出同一份 sceneLayersAt)", () => {
  it("底图轨此刻没有片段:上层的画中画仍是叠加层,不冒充底图去吃填充方式", () => {
    renderMonitor([
      track("V2", 0, [clip("pip", "V2", 0, 10)]),
      track("V1", 1, [clip("base", "V1", 5, 10)]),
    ]);
    act(() => useEditorStore.getState().setPlayhead(2));
    expect(layerSummary()).toEqual([{ clip: "pip", isBase: false }]);
    act(() => useEditorStore.getState().setPlayhead(6));
    expect(layerSummary()).toEqual([
      { clip: "base", isBase: true },
      { clip: "pip", isBase: false },
    ]);
  });

  it("最底下是一条只有花字的视频轨:真正的画面仍是底图", () => {
    const title = clip("title", "T", 0, 10, { asset_id: null, asset_kind: "", text_override: "Hi" });
    renderMonitor([
      track("V1", 0, [clip("picture", "V1", 0, 10)]),
      track("T", 1, [title]),
    ]);
    act(() => useEditorStore.getState().setPlayhead(1));
    expect(layerSummary()).toEqual([{ clip: "picture", isBase: true }]);
    expect(screen.queryByText("monitorBlankHint")).toBeNull();
  });
});

describe("层序与时间线一致", () => {
  it("按 position 合成:数组先后颠倒时,position 0 那条(时间线最上面一行)仍压在最上", () => {
    renderMonitor([
      track("V1", 1, [clip("base", "V1", 0, 10)]),
      track("V2", 0, [clip("top", "V2", 0, 10)]),
    ]);
    act(() => useEditorStore.getState().setPlayhead(1));
    expect(layerSummary()).toEqual([
      { clip: "base", isBase: true },
      { clip: "top", isBase: false },
    ]);
  });
});

describe("监视器走帧", () => {
  it("逐帧按钮按帧号走,时间码显示到帧", () => {
    renderMonitor([track("V1", 0, [clip("c1", "V1", 0, 10)])], 25);
    act(() => useEditorStore.getState().setPlayhead(1.01));
    fireEvent.click(screen.getByRole("button", { name: "monFrameForward" }));
    expect(useEditorStore.getState().playhead).toBe(26 / 25);
    fireEvent.click(screen.getByRole("button", { name: "monFrameBack" }));
    fireEvent.click(screen.getByRole("button", { name: "monFrameBack" }));
    expect(useEditorStore.getState().playhead).toBe(24 / 25);
    expect(screen.getByTestId("monitor-timecode").textContent).toBe("00:00:00:24 / 00:00:10:00");
  });
});

describe("画布上拖变换", () => {
  it("提交失败:草稿撤掉,画面回到已保存的变换", async () => {
    const onSetTransform = vi.fn(() => Promise.reject(new Error("locked")));
    renderMonitor([track("V1", 0, [clip("c1", "V1", 0, 10)])], 30, { onSetTransform });
    act(() => useEditorStore.getState().selectClip("c1"));
    const dragged = { scale: 2, x: 0, y: 0, rotation: 0, opacity: 1 };
    act(() => seen.overlay!.onChange(dragged));
    expect(seen.layers[0]?.transformOverride).toEqual(dragged);
    await act(async () => {
      seen.overlay!.onCommit(dragged);
      await Promise.resolve();
    });
    expect(onSetTransform).toHaveBeenCalledTimes(1);
    expect(seen.layers[0]?.transformOverride ?? null).toBeNull();
  });
});
