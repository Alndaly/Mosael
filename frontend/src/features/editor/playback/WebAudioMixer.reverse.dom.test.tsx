/** @vitest-environment jsdom */
/**
 * 主时钟在倒放(J)时的走法:播放头往回走、不出声,走到 0 停下。
 *
 * AudioContext 在 jsdom 里没有,换成一个时钟可控的假货;被测的是 WebAudioMixer 自己的计时循环。
 */
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WebAudioMixer, type AudioSourceSpec } from "@/features/editor/playback/WebAudioMixer";
import { useEditorStore } from "@/features/editor/editorStore";
import { livePlayhead } from "@/features/editor/playback/playbackClock";

const clock = { now: 0 };
const createdSources: Array<{ playbackRate: { value: number } }> = [];

class FakeAudioContext {
  state = "running";
  destination = {};
  get currentTime() {
    return clock.now;
  }
  createGain() {
    return { gain: { value: 1 }, connect: (next: unknown) => next };
  }
  createBufferSource() {
    const node = { buffer: null, playbackRate: { value: 1 }, connect: (next: unknown) => next, start: vi.fn(), stop: vi.fn() };
    createdSources.push(node);
    return node;
  }
  resume() {
    return Promise.resolve();
  }
  close() {
    return Promise.resolve();
  }
  decodeAudioData() {
    return Promise.resolve({ duration: 30 });
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  clock.now = 0;
  createdSources.length = 0;
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) })));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function tick(seconds: number) {
  clock.now += seconds;
  act(() => {
    vi.advanceTimersByTime(40);
  });
}

describe("倒放", () => {
  it("播放头往回走,到 0 停下,不排任何声音", () => {
    const sources: AudioSourceSpec[] = [
      { key: "a", assetId: "asset", srcIn: 0, srcOut: 20, timelineStart: 0, speed: 1, gain: 1 } as AudioSourceSpec,
    ];
    useEditorStore.setState({ playhead: 1, playing: true, playbackRate: -1, volume: 1, muted: false, loop: false });
    render(<WebAudioMixer sources={sources} totalDuration={20} />);
    tick(0); // 开一次会话
    tick(0.4);
    expect(useEditorStore.getState().playhead).toBeCloseTo(0.6);
    // 画面读的插值时钟也往回走(「只进不退」按播放方向算),不会卡在倒放开始的那一刻。
    expect(livePlayhead()).toBeLessThanOrEqual(0.6 + 1e-6);
    tick(0.8);
    expect(useEditorStore.getState()).toMatchObject({ playhead: 0, playing: false });
    expect(createdSources).toHaveLength(0);
  });
});
