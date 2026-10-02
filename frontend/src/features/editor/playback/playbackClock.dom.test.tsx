/** @vitest-environment jsdom */
/**
 * 播放中的画面时间按音频时钟插值,不再是混音器每 40ms 写一次 store 的阶梯。
 *
 * 混音器节拍之间,`livePlayhead()` 要按输出时间戳外推出连续的值;同一段播放里只往前走;没在播放时
 * 就是 store 里的值。
 */
import { act, cleanup, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useEditorStore } from "@/features/editor/editorStore";
import { livePlayhead } from "./playbackClock";
import { WebAudioMixer } from "./WebAudioMixer";

let perfNow = 1000;
const stamp = { contextTime: 0, performanceTime: 0 };
class FakeAudioContext {
  currentTime = 0;
  state = "running";
  destination = {};
  sampleRate = 48000;
  createGain() {
    const gain = { gain: { value: 1 }, connect: vi.fn(() => gain) };
    return gain;
  }
  getOutputTimestamp() {
    return { ...stamp };
  }
  async close() {}
}
const contexts: FakeAudioContext[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  perfNow = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => perfNow);
  vi.stubGlobal(
    "AudioContext",
    class extends FakeAudioContext {
      constructor() {
        super();
        contexts.push(this);
      }
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  useEditorStore.setState({ playing: false, playhead: 0, playbackRate: 1 });
});

async function tick(ctxTime: number) {
  const ctx = contexts[contexts.length - 1];
  ctx.currentTime = ctxTime;
  perfNow += 40;
  // 输出时间戳:扬声器此刻正放到 ctxTime(为了好算,不模拟输出延迟)。
  stamp.contextTime = ctxTime;
  stamp.performanceTime = perfNow;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(40);
  });
}

it("节拍之间按输出时间戳外推:画面拿到的是连续时间,不是 25fps 的阶梯", async () => {
  useEditorStore.setState({ playing: true, playhead: 1, playbackRate: 1, volume: 1, muted: false });
  render(<WebAudioMixer sources={[]} totalDuration={60} />);
  await tick(0); // 开一段播放,锚在 1s
  await tick(0.04);
  expect(useEditorStore.getState().playhead).toBeCloseTo(1.04, 6);

  const frames: number[] = [];
  for (let i = 1; i <= 2; i++) {
    perfNow += 16; // 两次 rAF,混音器的节拍还没到
    frames.push(livePlayhead());
  }
  expect(frames[0]).toBeCloseTo(1.056, 6);
  expect(frames[1]).toBeCloseTo(1.072, 6);
  // store 里还是上一拍的值:它只做低频同步。
  expect(useEditorStore.getState().playhead).toBeCloseTo(1.04, 6);
});

it("倍速按当前速率外推;时间戳抖回去时画面不倒退", async () => {
  useEditorStore.setState({ playing: true, playhead: 2, playbackRate: 2, volume: 1, muted: false });
  render(<WebAudioMixer sources={[]} totalDuration={60} />);
  await tick(0);
  perfNow += 10;
  const ahead = livePlayhead();
  expect(ahead).toBeCloseTo(2.02, 6);
  // 输出时间戳往回跳了一点(设备回调抖动):报出去的值不往回走。
  stamp.performanceTime = perfNow + 5;
  expect(livePlayhead()).toBeCloseTo(ahead, 6);
});

it("没在播放时就是 store 里的值", async () => {
  useEditorStore.setState({ playing: false, playhead: 3.5 });
  render(<WebAudioMixer sources={[]} totalDuration={60} />);
  await tick(0);
  perfNow += 500;
  expect(livePlayhead()).toBe(3.5);
});
