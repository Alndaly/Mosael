/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 灯箱里同一时刻只能有一个「活动源」。
 *
 * 维护者报的那一版:在剪辑页的素材面板里点开**第一个**视频,第二个视频的声音也一起响了。
 * 根因是 react-photo-view 的 PhotoSlider 会把当前项旁边的那一项也挂出来(prev/current/next,
 * 源码里是 `images.slice(index-1, index+2)`),而灯箱给每一项视频都渲染了一个 `autoPlay` 的
 * 播放器 —— 打开第一个,相邻那个也跟着开始播。
 *
 * 所以这里钉四件事:打开时只有一个媒体元素带源;翻页时旧的被卸掉(pause + 摘源);关掉之后
 * 一个都不剩;素材清单里音频和视频混在一起时,音频也不会偷偷挂出第二个播放器。
 */

//: 库按 `"ontouchstart" in window` 选手势那一套;jsdom 有这个属性,桌面版没有 —— 拿掉它,走鼠标那一套。
vi.hoisted(() => {
  for (let proto = Object.getPrototypeOf(window); proto; proto = Object.getPrototypeOf(proto)) {
    if (Object.prototype.hasOwnProperty.call(proto, "ontouchstart")) delete (proto as Record<string, unknown>).ontouchstart;
  }
  delete (window as unknown as Record<string, unknown>).ontouchstart;
});
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import { assetGallery } from "@/components/app/asset-preview";
import { assetFileUrl } from "@/api/client";

type Item = { src: string; title?: string; video?: boolean; assetId?: string };

function Opener({ item, gallery }: { item: Item; gallery?: Item[] }) {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ ...item, gallery })}>
      看大图
    </button>
  );
}

const portal = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const closeButton = () => screen.getByRole("button", { name: "imagePreviewClose" });
/** 所有**挂着源**的媒体元素 —— 这就是「可能会响」的那些。没有源的元素不会自己播。 */
const sources = () => [...document.querySelectorAll<HTMLMediaElement>(".PhotoView-Portal video[src], .PhotoView-Portal audio[src]")];
const srcs = () => sources().map((element) => element.getAttribute("src"));

async function open(item: Item, gallery?: Item[]) {
  render(
    <ImagePreviewProvider>
      <Opener item={item} gallery={gallery} />
    </ImagePreviewProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "看大图" }));
  await waitFor(() => expect(portal()).not.toBeNull());
}

/** 右边那颗翻页箭头(库自己画的 div,鼠标点)。 */
const nextArrow = () => document.querySelector<HTMLElement>(".PhotoView-Slider__ArrowRight")!;

const first = { src: "/files/one.mp4", title: "第一个视频", video: true, assetId: "one" };
const second = { src: "/files/two.mp4", title: "第二个视频", video: true, assetId: "two" };

afterEach(cleanup);

describe("灯箱的视频只让一个响", () => {
  it("① 点第一个视频:只有它一个挂着源,相邻那个不挂播放器", async () => {
    await open(first, [first, second]);

    await waitFor(() => expect(sources()).toHaveLength(1));
    expect(srcs()).toEqual([first.src]);
  });

  it("② 翻到第二个:第一个被卸掉(pause + 摘源),只有第二个挂着源", async () => {
    await open(first, [first, second]);
    await waitFor(() => expect(sources()).toHaveLength(1));
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause");

    fireEvent.click(nextArrow());

    await waitFor(() => expect(srcs()).toEqual([second.src]));
    expect(document.querySelector(`.PhotoView-Portal video[src="${first.src}"]`)).toBeNull();
    //: 不只是「换了一份 DOM」:旧元素是先被 pause、再摘掉 src 的,后台不会接着响。
    expect(pause).toHaveBeenCalled();
    pause.mockRestore();
  });

  it("③ 关掉灯箱:所有媒体元素都卸掉,并且是 pause + 摘源之后才走的", async () => {
    await open(first, [first, second]);
    await waitFor(() => expect(sources()).toHaveLength(1));
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause");

    fireEvent.click(closeButton());

    await waitFor(() => expect(document.querySelectorAll(".PhotoView-Portal video, .PhotoView-Portal audio")).toHaveLength(0));
    expect(document.querySelectorAll("video, audio")).toHaveLength(0);
    expect(pause).toHaveBeenCalled();
    pause.mockRestore();
  });

  it("④ 音频和视频混着用:灯箱一开,正在响的那条音频先停;画廊里仍只有一个视频带源", async () => {
    //: 灯箱的画廊按设计只收有画面的(见 components/app/asset-preview 的 assetGallery):音频不在里面。
    //: 所以清单是 [视频, 音频, 视频] 时,画廊里那两个视频挨在一起 —— 正是「点第一个、第二个也响」的形状;
    //: 而音频可能正在别处(素材引用/工具结果里的音频卡)就地播着,那一路也得让位。
    const gallery = assetGallery([
      { id: "one", kind: "video", name: "第一个视频" },
      { id: "voice", kind: "audio", name: "一段音频" },
      { id: "two", kind: "video", name: "第二个视频" },
    ]);
    expect(gallery.map((item) => item.src)).toEqual([assetFileUrl("one"), assetFileUrl("two")]);

    render(
      <ImagePreviewProvider>
        <audio data-outside-audio src="/files/voice.mp3" />
        <Opener item={gallery[0]!} gallery={gallery} />
      </ImagePreviewProvider>,
    );
    //: jsdom 不会真的播;把它标成「正在响」,灯箱打开时应该把它 pause 掉。
    const outside = document.querySelector<HTMLAudioElement>("[data-outside-audio]")!;
    Object.defineProperty(outside, "paused", { configurable: true, get: () => false });
    const pause = vi.spyOn(outside, "pause").mockImplementation(() => {});

    fireEvent.click(screen.getByRole("button", { name: "看大图" }));

    await waitFor(() => expect(pause).toHaveBeenCalled());
    await waitFor(() => expect(sources()).toHaveLength(1));
    expect(srcs()).toEqual([assetFileUrl("one")]);
    expect(document.querySelector(".PhotoView-Portal audio")).toBeNull();
    pause.mockRestore();
  });
});
