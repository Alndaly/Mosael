/** @vitest-environment jsdom */
import React from "react";
import { act, render, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WebAudioMixer, type AudioSourceSpec } from "./WebAudioMixer";
import { useEditorStore } from "@/features/editor/editorStore";
import { TINY_AUDIO_PROXY } from "./proxyFixtures";

const gains: { gain: { value: number }; connect: ReturnType<typeof vi.fn> }[] = [];
class FakeAudioContext {
  currentTime = 0;
  state = "running";
  destination = {};
  createGain() { const gain = { gain: { value: 1 }, connect: vi.fn(() => gain), disconnect: vi.fn() }; gains.push(gain); return gain; }
  createBuffer() { return { copyToChannel: vi.fn() }; }
  createBufferSource() { return { buffer: null, playbackRate: { value: 1 }, connect: (gain: unknown) => gain, start: vi.fn(), stop: vi.fn() }; }
  async close() {}
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); useEditorStore.getState().setPlaying(false); gains.length = 0; });

const spec = (over: Partial<AudioSourceSpec> = {}): AudioSourceSpec =>
  ({ key: "c", assetId: "a", audioProxy: "a:p", srcIn: 0, srcOut: 4, timelineStart: 0, speed: 1, gain: 1, muted: false, trackMuted: false, ...over }) as AudioSourceSpec;

it("sends amplified clip gain to the actual WebAudio graph", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(TINY_AUDIO_PROXY.slice(), { status: 206 })));
  useEditorStore.setState({ playing: true, playhead: 0.1, volume: 1, muted: false, playbackRate: 1 });
  render(<WebAudioMixer sources={[spec({ gain: 3 })]} totalDuration={4} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(120); });
  // master + 这一段的声部
  expect(gains.length).toBe(2);
  expect(gains[1].gain.value).toBe(3);
});

it("读不出来的音频代理只试一次:之后每一拍都不再重下(此前无声视频被每 40ms 整份重下一遍)", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  const fetchMock = vi.fn(async () => new Response(null, { status: 404 }));
  vi.stubGlobal("fetch", fetchMock);
  useEditorStore.setState({ playing: true, playhead: 0.1, volume: 1, muted: false, playbackRate: 1 });
  render(<WebAudioMixer sources={[spec()]} totalDuration={60} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("代理还没好的片段(audioProxy 为空,比如转码中或没有音轨):混音器一次都不去取", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  useEditorStore.setState({ playing: true, playhead: 0.1, volume: 1, muted: false, playbackRate: 1 });
  render(<WebAudioMixer sources={[spec({ audioProxy: null })]} totalDuration={60} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(fetchMock).not.toHaveBeenCalled();
});
