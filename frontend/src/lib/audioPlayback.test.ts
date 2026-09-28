/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { playBlob, stopPlayback } from "./audioPlayback";
import { useSamplePlayer } from "./useSamplePlayer";

/**
 * 朗读和试听共用**一个**「当前在响」。
 *
 * 此前两边各有一份「同一时刻只放一个」,彼此看不见:点了试听再点消息喇叭,两段人声叠在一起;
 * 免提对话里一开口本该掐掉正在响的声音,却掐不掉试听。
 */

const audios: FakeAudio[] = [];

class FakeAudio {
  src = "";
  currentTime = 0;
  paused = true;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onpause: (() => void) | null = null;
  constructor(src = "") {
    this.src = src;
    audios.push(this);
  }
  play() {
    this.paused = false;
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.onpause?.();
  }
}

beforeEach(() => {
  audios.length = 0;
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
});
afterEach(() => {
  stopPlayback();
  vi.unstubAllGlobals();
});

describe("全应用同一时刻只响一段", () => {
  it("试听在放时开始朗读,试听停下", () => {
    const { result } = renderHook(() => useSamplePlayer((id) => `/sample/${id}`));
    act(() => result.current.toggle("v1"));
    const sample = audios[0];
    expect(sample.paused).toBe(false);

    act(() => void playBlob(new Blob(["x"])));

    expect(sample.paused).toBe(true);
    expect(result.current.playingId).toBeNull();
  });

  it("朗读在放时开始试听,朗读停下并落定", async () => {
    const { result } = renderHook(() => useSamplePlayer((id) => `/sample/${id}`));
    let spoken = false;
    const speech = playBlob(new Blob(["x"])).then(() => {
      spoken = true;
    });

    act(() => result.current.toggle("v1"));
    await speech;

    expect(spoken).toBe(true);
    expect(audios[0].paused).toBe(true);
  });

  it("打断掐得掉试听", () => {
    const { result } = renderHook(() => useSamplePlayer((id) => `/sample/${id}`));
    act(() => result.current.toggle("v1"));

    act(() => stopPlayback());

    expect(audios[0].paused).toBe(true);
    expect(result.current.playingId).toBeNull();
  });
});
