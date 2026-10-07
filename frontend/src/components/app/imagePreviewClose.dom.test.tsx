/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 大图怎么关:每一张(图、视频,单张、成组)右上角都有一颗一直看得见、能用键盘按、带悬停说明的关闭键;点画面外面的背景
 * 也关;点视频的控件只管播放,不关。
 *
 * 维护者报的那一版:视频的大图只有 Esc 关得掉 —— 库自带的 ✕ 在顶上那一条里,点一下画面(视频的播放 / 暂停也算)那一条
 * 就淡出去;视频铺满了整个视口,没有背景可点。
 */

//: 库在载入时按 `"ontouchstart" in window` 挑触屏还是鼠标的那一套手势;jsdom 有这个属性,桌面版(Electron)没有 ——
//: 拿掉它,测的就是桌面上鼠标点的那一套。
vi.hoisted(() => {
  for (let proto = Object.getPrototypeOf(window); proto; proto = Object.getPrototypeOf(proto)) {
    if (Object.prototype.hasOwnProperty.call(proto, "ontouchstart")) delete (proto as Record<string, unknown>).ontouchstart;
  }
  delete (window as unknown as Record<string, unknown>).ontouchstart;
});
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, fitVideo, useImagePreview } from "@/components/app/image-preview";

type Item = { src: string; title?: string; video?: boolean };

function Opener({ item, gallery }: { item: Item; gallery?: Item[] }) {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ ...item, gallery })}>
      看大图
    </button>
  );
}

const portal = () => document.querySelector<HTMLElement>(".PhotoView-Portal");
const closing = () => portal()?.classList.contains("PhotoView-Slider__willClose") ?? true;
const closeButton = () => screen.getByRole("button", { name: "imagePreviewClose" });

async function open(item: Item, gallery?: Item[]) {
  render(
    <ImagePreviewProvider>
      <Opener item={item} gallery={gallery} />
    </ImagePreviewProvider>,
  );
  const opener = screen.getByRole("button", { name: "看大图" });
  opener.focus();
  fireEvent.click(opener);
  await waitFor(() => expect(portal()).not.toBeNull());
  return opener;
}

/** 库认「点」是按下、在同一处松开(松开听在 window 上)。 */
function tap(element: Element) {
  fireEvent.mouseDown(element, { button: 0, clientX: 5, clientY: 5 });
  fireEvent.mouseUp(window, { button: 0, clientX: 5, clientY: 5 });
  fireEvent.click(element, { button: 0, clientX: 5, clientY: 5 });
}

afterEach(cleanup);

describe("大图的关闭键", () => {
  it("单张图:右上角一颗关闭键,打开就拿到焦点,写着能按 Esc;点它关掉,焦点回到点开它的按钮", async () => {
    const opener = await open({ src: "/preview/a", title: "一张图" });
    const close = closeButton();
    expect(close.className).toMatch(/\bfixed\b/);
    expect(close.className).toMatch(/\bright-2\b/);
    expect(close.className).toMatch(/\btop-1\.5\b/);
    expect(close.className, "压在大图那一层(z-220)上面").toMatch(/\bz-\[221\]/);
    await waitFor(() => expect(document.activeElement).toBe(close));
    fireEvent.click(close);
    await waitFor(() => expect(closing()).toBe(true));
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("关闭键的悬停说明画在大图那一层之上(不交给原生视图上面的浮层视图)", async () => {
    await open({ src: "/preview/a" });
    const close = closeButton();
    fireEvent.pointerMove(close, { pointerType: "mouse" });
    const hint = await screen.findByRole("tooltip", {}, { timeout: 2_000 });
    const content = hint.closest("[data-tooltip]") ?? document.querySelector("[data-tooltip]");
    expect(content?.hasAttribute("data-over-lightbox")).toBe(true);
    expect(content?.hasAttribute("data-over-chrome")).toBe(false);
    expect(document.querySelector("[data-tooltip]")?.textContent).toContain("imagePreviewClose");
  });

  it("成组翻:关闭键一直在;库自带那个点一下画面就淡出去的 ✕ 藏起来", async () => {
    const gallery = [{ src: "/preview/a" }, { src: "/preview/b" }];
    await open(gallery[1], gallery);
    expect(portal()?.textContent).toContain("2 / 2");
    expect(closeButton()).toBeInTheDocument();
    expect(portal()!.className).toContain("[&_.PhotoView-Slider\\_\\_BannerRight>.PhotoView-Slider\\_\\_toolbarIcon]:hidden");
    //: 点一下画面:库把顶上那一条淡出去(clean),关闭键不在那一条里,照样在
    tap(portal()!.querySelector(".PhotoView__PhotoBox img, .PhotoView__Photo")!);
    await waitFor(() => expect(portal()!.classList.contains("PhotoView-Slider__clean")).toBe(true));
    expect(closeButton()).toBeInTheDocument();
    expect(closing()).toBe(false);
  });

  it("图:点画面外面的背景关掉", async () => {
    await open({ src: "/preview/a" });
    tap(portal()!.querySelector(".PhotoView__PhotoWrap")!);
    await waitFor(() => expect(closing()).toBe(true));
  });

  it("视频:关闭键在;点播放器四周的背景关掉;点画面、点控件只管播放,不关", async () => {
    await open({ src: "/preview/clip.mp4", title: "一段视频", video: true });
    expect(closeButton()).toBeInTheDocument();
    const frame = portal()!.querySelector<HTMLElement>("[data-video-frame]")!;
    const backdrop = portal()!.querySelector<HTMLElement>("[data-video-backdrop]")!;
    expect(backdrop.contains(frame)).toBe(true);
    expect(backdrop.className, "盒子不要图片的圆角、描边").not.toContain("rounded-lg");

    const video = frame.querySelector("video")!;
    tap(video);
    for (const control of frame.querySelectorAll("button")) tap(control);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(closing(), "点在播放器里不关").toBe(false);

    tap(backdrop);
    await waitFor(() => expect(closing()).toBe(true));
  });

  it("视频按自己的宽高比收进视口:读到自然尺寸前按 16:9,横的竖的都整个看得见", async () => {
    await open({ src: "/preview/tall.mp4", video: true });
    const frame = portal()!.querySelector<HTMLElement>("[data-video-frame]")!;
    const video = frame.querySelector("video")!;
    Object.defineProperty(video, "videoWidth", { value: 720 });
    Object.defineProperty(video, "videoHeight", { value: 1280 });
    Object.defineProperty(video, "duration", { value: 4 });
    act(() => void fireEvent.loadedMetadata(video));
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    await waitFor(() => expect(frame.style.width).toBe(`${fitVideo({ width: 720, height: 1280 }, viewport).width}px`));
  });
});

describe("fitVideo", () => {
  it("收进视口减去四周留边的那一块,按比例放大缩小", () => {
    expect(fitVideo({ width: 1920, height: 1080 }, { width: 1280, height: 800 })).toEqual({ width: 1195, height: 672 });
    expect(fitVideo({ width: 2400, height: 800 }, { width: 1280, height: 800 }), "很宽的:宽度顶满").toEqual({ width: 1216, height: 405 });
    expect(fitVideo({ width: 720, height: 1280 }, { width: 1280, height: 800 })).toEqual({ width: 378, height: 672 });
    expect(fitVideo({ width: 512, height: 288 }, { width: 1280, height: 800 }), "小的也放大到看得清").toEqual({ width: 1195, height: 672 });
    expect(fitVideo(undefined, { width: 1280, height: 800 }), "还不知道尺寸:16:9").toEqual({ width: 1195, height: 672 });
  });
});
