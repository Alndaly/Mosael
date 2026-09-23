/**
 * 拖进度条时沿途的跳转合并掉,只跳到最新的位置。
 * 此前每次指针移动都设一次 currentTime:大录屏单次跳转 0.3–0.6 秒,一次拖动排几十个,
 * 画面冻住,松手后还要等它们挨个过完。
 */
import { expect, it } from "vitest";
import { seekTo } from "./coalescedSeek";

function fakeMedia() {
  const listeners: Array<() => void> = [];
  const sets: number[] = [];
  let time = 0;
  const media = {
    seeking: false,
    get currentTime() { return time; },
    set currentTime(value: number) { time = value; sets.push(value); media.seeking = true; },
    addEventListener: (_type: string, listener: () => void) => listeners.push(listener),
    land() { media.seeking = false; listeners.splice(0).forEach((listener) => listener()); },
  };
  return { media, sets };
}

it("上一次跳转没落地时,中间的位置都不跳,落地后直接跳到最新的", () => {
  const { media, sets } = fakeMedia();
  seekTo(media as unknown as HTMLMediaElement, 10);
  seekTo(media as unknown as HTMLMediaElement, 20);
  seekTo(media as unknown as HTMLMediaElement, 30);
  seekTo(media as unknown as HTMLMediaElement, 40);
  expect(sets).toEqual([10]);

  media.land();
  expect(sets).toEqual([10, 40]);
  media.land();
  expect(sets).toEqual([10, 40]);
});

it("没在跳转时立刻跳", () => {
  const { media, sets } = fakeMedia();
  seekTo(media as unknown as HTMLMediaElement, 5);
  media.land();
  seekTo(media as unknown as HTMLMediaElement, 7);
  expect(sets).toEqual([5, 7]);
});
