/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSamplePlayer } from "./useSamplePlayer";

/**
 * 试听是**开关**,不是单向动作。
 *
 * 音色库里那个 ▷ 只会调 `audio.play()`:按下去开始放,再按一次还是从头开始放,没有任何办法
 * 让它停。参考音频是 5–15 秒的人声,放到一半想停下来看别的,只能等它自己放完 —— 或者切走页面,
 * 而切走它还在响(那个 `Audio` 对象没人负责关)。
 *
 * 一个按下去没法收回的按钮,和一个不显示当前状态的按钮,是同一个毛病的两面。
 */

const played: string[] = [];
let paused = 0;

class FakeAudio {
  src = "";
  currentTime = 0;
  onended: (() => void) | null = null;
  onpause: (() => void) | null = null;
  play() {
    played.push(this.src);
    return Promise.resolve();
  }
  pause() {
    paused += 1;
    this.onpause?.();
  }
}

beforeEach(() => {
  played.length = 0;
  paused = 0;
  vi.stubGlobal("Audio", FakeAudio);
});
afterEach(() => vi.unstubAllGlobals());

const url = (id: string) => `/sample/${id}`;

describe("试听", () => {
  it("按一下开始放,并且说得出在放哪一个", () => {
    const { result } = renderHook(() => useSamplePlayer(url));

    act(() => result.current.toggle("v1"));

    expect(played).toEqual(["/sample/v1"]);
    expect(result.current.playingId).toBe("v1");
  });

  it("再按一下停下来 —— 这是用户报的那个问题", () => {
    const { result } = renderHook(() => useSamplePlayer(url));

    act(() => result.current.toggle("v1"));
    act(() => result.current.toggle("v1"));

    expect(paused).toBe(1);
    expect(result.current.playingId).toBeNull();
  });

  it("按另一个就换成另一个,而不是两个一起响", () => {
    const { result } = renderHook(() => useSamplePlayer(url));

    act(() => result.current.toggle("v1"));
    act(() => result.current.toggle("v2"));

    expect(paused).toBe(1);
    expect(played).toEqual(["/sample/v1", "/sample/v2"]);
    expect(result.current.playingId).toBe("v2");
  });

  it("放完了自己复位 —— 否则按钮会一直停在「正在放」", () => {
    const { result } = renderHook(() => useSamplePlayer(url));
    act(() => result.current.toggle("v1"));

    act(() => result.current._audio()?.onended?.(new Event("ended")));

    expect(result.current.playingId).toBeNull();
  });

  it("同一个音色再放一次是从头开始", () => {
    const { result } = renderHook(() => useSamplePlayer(url));
    act(() => result.current.toggle("v1"));
    act(() => result.current.toggle("v1"));

    act(() => result.current.toggle("v1"));

    expect(result.current._audio()?.currentTime).toBe(0);
    expect(result.current.playingId).toBe("v1");
  });

  it("组件卸载时把声音关掉 —— 切走页面它还在响是没人负责的那种 bug", () => {
    const { result, unmount } = renderHook(() => useSamplePlayer(url));
    act(() => result.current.toggle("v1"));

    unmount();

    expect(paused).toBe(1);
  });
});
