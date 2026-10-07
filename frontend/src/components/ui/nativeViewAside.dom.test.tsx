/** @vitest-environment jsdom */

/**
 * 原生网页视图(内嵌浏览器、ComfyUI 工作台)盖在一切 DOM 上:大图开着时请主进程把它挪到窗口外,关掉时放回 —— 不然整窗的
 * 大图只露得出顶栏和侧栏那几条,图被画布盖住(维护者在工作台里点结果缩略图时就是这样)。
 *
 * 挪开之前先在原处铺一张网页此刻的画面:不铺的话,视图挪走的那一下露出来的是空着的应用背景(浮层还没淡入),画布闪没了
 * (维护者在工作台模型库里点缩略图时看到的)。放回时反过来:先放回视图,再拿掉画面。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import { NativeViewStandIn, resetNativeViewAside, stepNativeViewAside } from "@/components/ui/nativeViewAside";

function Opener() {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ src: "preview://a1", title: "PreviewImage #12 · 1/2",
                                                            gallery: [{ src: "preview://a1" }, { src: "preview://a2" }] })}>
      看大图
    </button>
  );
}

const BOUNDS = { x: 0, y: 56, width: 1020, height: 844 };
const FRAME = "data:image/jpeg;base64,ZnJhbWU=";

/**
 * 主进程那一侧:按先后记下发生了什么(拍画面、挪开、放回),以及那一刻屏幕上(DOM 里)画面在不在、加载好了没有。
 * 挪开 / 放回要过一阵才完成(主进程挪视图、下一帧合成):过一会儿再看 DOM,看到的就是那时候人眼里的样子。
 */
let log: string[];
let setOverlay: ReturnType<typeof vi.fn>;
let snapshotPage: ReturnType<typeof vi.fn>;
const standIn = () => document.querySelector<HTMLImageElement>("[data-native-view-stand-in]");
const loadedFrames = new WeakSet<Element>();
const frameState = () => {
  const frame = standIn();
  return !frame ? "off" : loadedFrames.has(frame) ? "on" : "unloaded";
};
const settles = () => new Promise((resolve) => setTimeout(resolve, 20));

beforeEach(() => {
  log = [];
  setOverlay = vi.fn(async (up: boolean) => {
    await settles();
    log.push(`${up ? "aside" : "back"}:frame=${frameState()}`);
  });
  snapshotPage = vi.fn(async () => {
    log.push("snapshot");
    return { frame: FRAME, bounds: BOUNDS };
  });
  vi.stubGlobal("mosaelPublish", { setOverlay, snapshotPage });
});
afterEach(() => {
  cleanup();
  resetNativeViewAside();
  vi.unstubAllGlobals();
});

/** 画面「加载好了」:jsdom 不解码图片,替它发 load。先等一阵 —— 加载好之前视图不该挪开。 */
async function frameLoads() {
  const asideBefore = log.filter((one) => one.startsWith("aside")).length;
  await waitFor(() => expect(standIn()).not.toBeNull());
  await new Promise((resolve) => setTimeout(resolve, 60));
  expect(log.filter((one) => one.startsWith("aside")).length, "画面还没加载好:视图还在原处").toBe(asideBefore);
  loadedFrames.add(standIn()!);
  fireEvent.load(standIn()!);
}

describe("整窗的浮层亮着时,原生网页视图让开", () => {
  it("大图打开 → 先在原处铺好网页的画面,再挪开视图;关掉 → 先放回视图,再拿掉画面;焦点回到点开它的那个按钮", async () => {
    render(
      <ImagePreviewProvider>
        <Opener />
        <NativeViewStandIn />
      </ImagePreviewProvider>,
    );
    expect(setOverlay).not.toHaveBeenCalled();
    const opener = screen.getByRole("button", { name: "看大图" });
    opener.focus();
    fireEvent.click(opener);
    await frameLoads();
    const frame = standIn()!;
    expect(frame.getAttribute("src")).toBe(FRAME);
    expect([frame.style.left, frame.style.top, frame.style.width, frame.style.height], "铺在视图原来那一块")
      .toEqual(["0px", "56px", "1020px", "844px"]);
    expect(frame.className, "在页面之上、外壳(z-190 / 200)和浮层之下;不接指针").toMatch(/\bz-\[188\].*pointer-events-none|pointer-events-none.*\bz-\[188\]/);
    await waitFor(() => expect(log, "画面铺上了才挪开").toEqual(["snapshot", "aside:frame=on"]));
    const viewer = document.querySelector<HTMLElement>(".PhotoView-Portal")!;
    expect(viewer.className, "压过窗口外壳(z-200)和它的说明(z-210)").toMatch(/\bz-\[220\]/);
    expect(viewer.className, "开着时不当拖拽区(关闭键在顶栏那一条上)").toContain("[-webkit-app-region:no-drag]");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(log.at(-1), "放回视图时画面还铺着(视图先盖住它)").toBe("back:frame=on"));
    await waitFor(() => expect(standIn(), "放回之后才拿掉").toBeNull());
    expect(setOverlay).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("画面迟迟加载不好也不让浮层一直被视图盖着:等够一阵照样挪开", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "requestAnimationFrame"] });
    try {
      render(<NativeViewStandIn />);
      act(() => void stepNativeViewAside());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      expect(standIn()).not.toBeNull();
      expect(setOverlay).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_100);
      });
      expect(setOverlay).toHaveBeenCalledWith(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("没有前台网页(拍不到画面):只请主进程记一笔,什么都不铺", async () => {
    snapshotPage.mockImplementation(async () => {
      log.push("snapshot");
      return null;
    });
    render(<NativeViewStandIn />);
    const release = stepNativeViewAside();
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=off"]));
    expect(standIn()).toBeNull();
    release();
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=off", "back:frame=off"]));
  });

  it("几处同时要它让开:只拍一次、只挪一次;最后一处收起才放回;放两次只算一次", async () => {
    render(<NativeViewStandIn />);
    const first = stepNativeViewAside();
    const second = stepNativeViewAside();
    await frameLoads();
    await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true]]));
    expect(snapshotPage).toHaveBeenCalledTimes(1);
    first();
    first();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(setOverlay.mock.calls, "还有一处要它让开").toEqual([[true]]);
    act(() => second());
    await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true], [false]]));
    await waitFor(() => expect(standIn()).toBeNull());
  });

  it("拍画面的这一会儿就收起了(点开马上又关):不挪、不铺", async () => {
    render(<NativeViewStandIn />);
    const release = stepNativeViewAside();
    release();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(log).toEqual(["snapshot"]);
    expect(standIn()).toBeNull();
  });

  it("挪开的路上收起了:挪完接着放回,画面最后拿掉;收起之后又打开:重新拍一张", async () => {
    let moved: () => void = () => undefined;
    setOverlay.mockImplementationOnce(async (up: boolean) => {
      log.push(`${up ? "aside" : "back"}:frame=${frameState()}`);
      await new Promise<void>((resolve) => {
        moved = resolve;
      });
    });
    render(<NativeViewStandIn />);
    const release = stepNativeViewAside();
    await frameLoads();
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=on"]));
    release();
    moved();
    await waitFor(() => expect(log).toEqual(["snapshot", "aside:frame=on", "back:frame=on"]));
    await waitFor(() => expect(standIn()).toBeNull());
    const again = stepNativeViewAside();
    await frameLoads();
    await waitFor(() => expect(log.slice(3)).toEqual(["snapshot", "aside:frame=on"]));
    again();
    await waitFor(() => expect(standIn()).toBeNull());
  });

  it("网页版(没有这座桥):什么都不做", () => {
    vi.stubGlobal("mosaelPublish", undefined);
    const release = stepNativeViewAside();
    release();
    expect(setOverlay).not.toHaveBeenCalled();
    expect(snapshotPage).not.toHaveBeenCalled();
  });
});
