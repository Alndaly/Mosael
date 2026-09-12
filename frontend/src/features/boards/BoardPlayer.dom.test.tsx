/** @vitest-environment jsdom */
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 画板上的视频:**离屏就把 `<video>` 卸掉**。
 *
 * 一个 `<video>` 占着一个解码器,Chrome 每页大约只给 75 个。画板是最容易摆上一百个节点的
 * 地方,而超出上限之后后面那些**不报错**,就是一直黑着 —— 用户会以为素材坏了。
 *
 * 这里钉的是这件事里容易反过来做错的几处:缩得太小时也该卸(不然"适应画布"一下全挂上)、
 * 缩放停下要重新量(IntersectionObserver 在这件事上会漏)、正在播的不能卸(等于替用户
 * 按了停止)、卸了再挂要接着播、以及没有观察器时宁可全挂上。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));

//: 画板节点住在 React Flow 里,而这条测试不想为了一个播放器立起整张画布 ——
//: 把「缩放停下了」这个信号接出来,测试自己叫。
let viewportEnded: Array<() => void> = [];
vi.mock("@xyflow/react", () => ({
  useOnViewportChange: ({ onEnd }: { onEnd?: () => void }) => {
    if (onEnd) viewportEnded.push(onEnd);
  },
}));

import { BoardVideo, shouldMountVideo } from "@/features/boards/BoardPlayer";

type Watcher = (entries: Array<{ boundingClientRect: DOMRect }>) => void;
let watchers: Watcher[] = [];

/** 节点此刻在屏幕上的位置和大小。视口固定成 1000×800。 */
function rectOf(left: number, top: number, width: number): DOMRect {
  return {
    left, top, width, height: width * 0.5,
    right: left + width, bottom: top + width * 0.5,
    x: left, y: top, toJSON: () => ({}),
  } as DOMRect;
}

/** 让测试自己说"现在画在哪儿、画多大"。 */
function place(rect: DOMRect, { via = "observer" }: { via?: "observer" | "viewport" } = {}) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(rect);
  act(() => {
    if (via === "observer") for (const watch of watchers) watch([{ boundingClientRect: rect }]);
    else for (const end of viewportEnded) end();
  });
}

beforeEach(() => {
  watchers = [];
  viewportEnded = [];
  vi.stubGlobal("innerWidth", 1000);
  vi.stubGlobal("innerHeight", 800);
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: Watcher) {
        watchers.push(callback);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
      takeRecords() {
        return [];
      }
    },
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const video = () => document.querySelector("video");

describe("值不值得占一个解码器", () => {
  const viewport = { width: 1000, height: 800 };

  it("在视野里、够大 —— 挂", () => {
    expect(shouldMountVideo(rectOf(100, 100, 320), viewport)).toBe(true);
  });

  it("在视野里但太小 —— 不挂", () => {
    // 「适应画布」时整张画板都相交,只按相交判会把一百个一起挂上。
    expect(shouldMountVideo(rectOf(100, 100, 40), viewport)).toBe(false);
  });

  it("够大但远在视野之外 —— 不挂", () => {
    expect(shouldMountVideo(rectOf(100, 4000, 320), viewport)).toBe(false);
    expect(shouldMountVideo(rectOf(-5000, 100, 320), viewport)).toBe(false);
  });

  it("差一点点进视野 —— 提前挂上,免得闪一下", () => {
    expect(shouldMountVideo(rectOf(100, 900, 320), viewport)).toBe(true);
    expect(shouldMountVideo(rectOf(100, 1200, 320), viewport)).toBe(false);
  });
});

describe("画板视频离屏卸载", () => {
  it("一开始不挂,画的是这份素材的封面", () => {
    render(<BoardVideo assetId="a1" />);
    expect(video()).toBeNull();
    // 封面而不是一片黑:拖动画布时不该看见节点在"有画面"和"全黑"之间闪。
    expect(screen.getByRole("presentation", { hidden: true })).toHaveAttribute("src", "/thumb/a1");
  });

  it("进了视野才挂上,离开又卸掉", () => {
    render(<BoardVideo assetId="a1" />);
    place(rectOf(100, 100, 320));
    expect(video()).not.toBeNull();
    place(rectOf(100, 4000, 320));
    expect(video()).toBeNull();
  });

  it("缩放停下要重新量 —— 光靠 IntersectionObserver 会漏", () => {
    // 实测过:一个**始终**在视野里的节点,从 0.15 倍拉回 1 倍,观察器全程一次都不叫。
    // 只认观察器的话,从总览缩放回来之后这些节点会卡在封面上再也不挂播放器。
    render(<BoardVideo assetId="a1" />);
    place(rectOf(100, 100, 40));
    expect(video()).toBeNull();
    place(rectOf(100, 100, 320), { via: "viewport" });
    expect(video()).not.toBeNull();
  });

  it("正在播的那个离屏也不卸", () => {
    render(<BoardVideo assetId="a1" />);
    place(rectOf(100, 100, 320));
    fireEvent.play(video()!);
    place(rectOf(100, 4000, 320));
    // 你可能正一边听着它一边把画布拖去看别处 —— 卸掉等于替用户按了停止。
    expect(video()).not.toBeNull();
    fireEvent.pause(video()!);
    expect(video()).toBeNull();
  });

  it("卸了再挂回来,接着上次的位置", () => {
    render(<BoardVideo assetId="a1" />);
    place(rectOf(100, 100, 320));
    const element = video()!;
    Object.defineProperty(element, "currentTime", { value: 42, writable: true, configurable: true });
    fireEvent.timeUpdate(element);
    place(rectOf(100, 4000, 320));
    place(rectOf(100, 100, 320));

    const again = video()!;
    Object.defineProperty(again, "duration", { value: 120, configurable: true });
    fireEvent.loadedMetadata(again);
    expect(again.currentTime).toBe(42);
  });

  it("封面取不到时退回纯黑,不露破损图", () => {
    // 缩略图是尽力而为的(ffmpeg 抽帧可能失败),而浏览器那张撕裂的图片图标既不说这里是什么,
    // 也不说出了什么事 —— 这次巡检刚在画板预览上修过同一个形状。
    render(<BoardVideo assetId="a1" />);
    fireEvent.error(screen.getByRole("presentation", { hidden: true }));
    expect(screen.queryByRole("presentation", { hidden: true })).toBeNull();
    expect(video()).toBeNull();
  });

  it("没有观察器就一律挂上", () => {
    // 兜底不是优化:宁可占解码器,也不能让画板上的视频**根本不出现**。
    vi.stubGlobal("IntersectionObserver", undefined);
    render(<BoardVideo assetId="a1" />);
    expect(video()).not.toBeNull();
  });
});
