/** @vitest-environment jsdom */
/**
 * 视频对比:几条视频一起播。比的是「同一时刻」各条长什么样,所以控制只有一套、时间只有一条。
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({ assetFileUrl: (id: string) => `/file/${id}` }));

import type { Asset } from "@/api/client";
import { VideoCompareView } from "./VideoCompareView";

const video = (id: string, duration: number) =>
  ({ id, name: `clip-${id}`, kind: "video", media_info: { duration, width: 1280, height: 720, fps: 25 } }) as unknown as Asset;

const played: string[] = [];
beforeEach(() => {
  played.length = 0;
  // jsdom 没有媒体播放:play / pause 记下来就行。
  Object.defineProperty(HTMLMediaElement.prototype, "play", {
    configurable: true,
    value(this: HTMLVideoElement) { played.push(this.getAttribute("src") ?? ""); return Promise.resolve(); },
  });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value() {} });
});

function renderView() {
  render(<VideoCompareView assets={[video("a", 5), video("b", 8), video("c", 3)]} onClose={vi.fn()} />);
  return [...document.querySelectorAll("video")];
}

it("几条视频铺在一屏,一个播放键让它们一起播", () => {
  const videos = renderView();
  expect(videos).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "videoComparePlay" }));
  expect(played.sort()).toEqual(["/file/a", "/file/b", "/file/c"]);
});

it("默认都静音;点某一条的喇叭只听它", () => {
  const videos = renderView();
  expect(videos.every((element) => element.muted)).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "videoCompareListen: clip-b" }));
  expect(videos.map((element) => element.muted)).toEqual([true, false, true]);
});

it("逐帧和拖时间轴都作用在所有条上;短的停在它自己的最后一帧", () => {
  const videos = renderView();
  fireEvent.click(screen.getByRole("button", { name: "videoCompareNextFrame" }));
  expect(videos.map((element) => element.currentTime)).toEqual([0.04, 0.04, 0.04]);

  fireEvent.change(screen.getByRole("slider", { name: "videoCompareSeek" }), { target: { value: "6" } });
  const [a, b, c] = videos.map((element) => element.currentTime);
  expect(b).toBe(6);
  expect(a).toBeCloseTo(5, 2);
  expect(c).toBeCloseTo(3, 2);
});
