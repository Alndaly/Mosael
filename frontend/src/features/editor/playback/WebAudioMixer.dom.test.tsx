/** @vitest-environment jsdom */
import React from "react";
import { act, render, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WebAudioMixer, type AudioSourceSpec } from "./WebAudioMixer";
import { useEditorStore } from "@/stores/editorStore";

const gains: { gain: { value: number }; connect: ReturnType<typeof vi.fn> }[] = [];
class FakeAudioContext {
  currentTime = 0;
  state = "running";
  destination = {};
  createGain() { const gain = { gain: { value: 1 }, connect: vi.fn(() => gain) }; gains.push(gain); return gain; }
  createBufferSource() { return { buffer: null, playbackRate: { value: 1 }, connect: (gain: unknown) => gain, start: vi.fn(), stop: vi.fn() }; }
  async decodeAudioData() { return { duration: 10 }; }
  async close() {}
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); useEditorStore.getState().setPlaying(false); gains.length = 0; });
it("sends amplified clip gain to the actual WebAudio graph", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) })));
  useEditorStore.setState({ playing: true, playhead: 1, volume: 1, muted: false, playbackRate: 1 });
  render(<WebAudioMixer sources={[{ key: "c", assetId: "a", srcIn: 0, srcOut: 4, timelineStart: 0, speed: 1, gain: 3, muted: false, trackMuted: false } as AudioSourceSpec]} totalDuration={4} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(120); });
  expect(gains.length).toBe(2);
  expect(gains[1].gain.value).toBe(3);
});
