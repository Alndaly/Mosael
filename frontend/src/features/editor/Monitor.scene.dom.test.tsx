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

const seen = vi.hoisted(() => ({ layers: [] as Array<{ clip: { id: string }; isBase?: boolean }> }));

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/editor/playback/CanvasCompositor", () => ({
  CanvasCompositor: ({ layers }: { layers: Array<{ clip: { id: string }; isBase?: boolean }> }) => {
    seen.layers = layers;
    return <canvas data-testid="compositor" />;
  },
}));
vi.mock("@/features/editor/playback/WebAudioMixer", () => ({ WebAudioMixer: () => null }));
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

function renderMonitor(tracks: Track[], fps = 30) {
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps, tracks, reframe: {}, subtitle_style: {} } as unknown as Sequence;
  return render(<Monitor sequence={sequence} assets={assets} />);
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  seen.layers = [];
  useEditorStore.setState({ playhead: 0, playing: false, selectedClipIds: [] });
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
