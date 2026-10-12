/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { expect, vi } from "vitest";

import { PreferencesProvider } from "@/app/preferences";
import { MaskEditor, isMaskCanvas } from "@/components/generation/MaskEditor";
import { PixelCanvas, PixelImage, registerPixelImage } from "@/test/pixelCanvas";
import { canvasesOfSize, installPixelCanvas, pixelOf } from "@/test/pixelCanvasSetup";

/**
 * jsdom 那一侧的**像素级**蒙版编辑器台架。
 *
 * ## 为什么另起一份(而不是接着用 MaskEditor.dom.test.tsx 里那个只记账的替身)
 *
 * 维护者报的那一族(清空 / 撤销 / 反选 / 形状 / 橡皮)全都是**像素层面**的:蒙版里有没有漏出
 * `alpha 0`、没画过的地方是不是逐字节等于原图 —— 只记调用、像素给全 0 的替身一条也测不出来。
 * 这里换成 `src/test/pixelCanvas` 那份**真的会算**的替身(`source-over` / `difference` /
 * `multiply` / `lighter` + `globalAlpha` 都按规范算),于是:
 *
 * - 可见画布上"没画过的那一格"能被断言成**逐字节等于原图**;
 * - 蒙版里"有没有透明像素"能被断言成**每个像素 alpha 255**。
 *
 * 底图走的是组件的真实那条路(fetch → blob → Image → drawImage),所以 `alpha` 那一层也在里面。
 */

/** 一张底图:左边 2/3 纯蓝、右边 1/3 纯红 —— 两种底色都远离白/黑,合成出什么一眼分得清。 */
export function buildUnderlay(width: number, height: number): PixelImage {
  const image = new PixelImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const at = (y * width + x) * 4;
      const blue = x < (width * 2) / 3;
      image.data[at] = blue ? 0 : 255;
      image.data[at + 1] = 0;
      image.data[at + 2] = blue ? 255 : 0;
      image.data[at + 3] = 255;
    }
  }
  return image;
}

export interface PixelHarness {
  /** 底图那份像素(断言"逐字节等于原图"的参照)。 */
  underlay: PixelImage;
  /** 底图那个 `Image`(测试拿它去挂像素)。 */
  images: HTMLImageElement[];
  /** 底图那份像素挂着的源对象(`loadImage` 用它读"底图像素")。 */
  source: HTMLCanvasElement;
  /** 可见那张画布和它的像素。 */
  view(): HTMLCanvasElement;
  viewPixels(): PixelCanvas;
  /** 离屏蒙版那张(不在 DOM 里、尺寸等于文档)。 */
  mask(): HTMLCanvasElement;
  maskPixels(): PixelCanvas;
  /** 可见画布上那次 `paint()` 做过什么(顺序 + 混合方式 + alpha)。 */
  viewCalls(): string[];
  /** 把微任务放干净:`createMaskWriter` 的不透明校验排在微任务里(拖动期间不做整张读回)。 */
  settle(): Promise<void>;
  /** 读一个**文档坐标**上的像素。 */
  sample(canvas: HTMLCanvasElement, x: number, y: number): number[];
  mount(): { onOpenChange: ReturnType<typeof vi.fn>; onDone: ReturnType<typeof vi.fn> };
  /** 「底图读完了」—— 组件用那两个初始化键的表态。 */
  ready(): boolean;
  /** 这一座的范围:那个弹窗(弹窗里的控件都从这里查)。 */
  scope(): ReturnType<typeof within>;
}

/**
 * 把 jsdom 的画布换成"真有像素"的那一份,并把组件挂起来。
 *
 * 底图 = `size`;盒子量出 `box`(contain 那一套只影响 CSS 尺寸,像素断言按文档坐标走)。
 */
export function pixelHarness(options: { width: number; height: number; box?: { width: number; height: number } }): PixelHarness {
  const width = options.width;
  const height = options.height;
  //: **盒子 = 文档、dpr = 1**:contain 算出来的位图尺寸于是**正好**等于文档尺寸,可见画布上的
  //: 底图与蒙版都是 1:1(没有重采样)。断言要"逐字节等于原图",就必须先没有插值。
  const box = options.box ?? { width, height };
  const underlay = buildUnderlay(width, height);
  installPixelCanvas();
  //: **先清掉上一座**:Setup 文件里的自动 cleanup 只在真正 import 了它的文件里挂上,少了这一下
  //: 第二次 `mount()` 之后查询会摸到上一座那棵子树(实测:断言全打在旧画布的像素上)。
  cleanup();
  vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(1);
  //: 蒙版色是**主题 token**(`--destructive`),而 jsdom 里一张样式表都没有 —— 读不到就是空串,
  //: 于是"着色"那一层铺的是黑(等于空转),屏幕上只剩压暗那一笔。这里按 tokens.css 里那两套值
  //: 给一份(判据和真 CSS 一样:看 `<html>` 上有没有 `.dark`),`<html>` 上有的 class 就照真值。
  const realStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element: Element, pseudo?: string | null) => {
    const style = realStyle(element, pseudo);
    return new Proxy(style, {
      get(target, key) {
        if (key === "getPropertyValue") {
          return (property: string) =>
            property === "--destructive" ? (document.documentElement.classList.contains("dark") ? "#f28d96" : "#bd383e") : target.getPropertyValue(property);
        }
        const value = Reflect.get(target, key);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
  });
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(box.width);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(box.height);
  //: jsdom 没有版面(`getBoundingClientRect()` 全是 0),而 `docPoint` 正是靠它把屏幕坐标换成文档坐标。
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, box.width, box.height));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        this.callback();
      }
      unobserve() {}
      disconnect() {}
    },
  );

  //: `loadImage` 会把解码好的图片画进一张临时画布再 `getImageData`(见 MaskEditor 的 loadImage)。
  //: 那张临时画布读的也是这份替身 —— 先按**元素**把"这张 `<img>` 是什么像素"登记好,否则读回来全 0
  //: (底图读成黑的,「按亮度初始化」就整张不变 —— 实测踩过)。
  const sourceElement = document.createElement("canvas");
  sourceElement.width = width;
  sourceElement.height = height;
  registerPixelImage(sourceElement, underlay);

  //: 底图走组件真实那条路:fetch → blob → Image。解码由测试决定什么时候"完成"。
  const decoded: HTMLImageElement[] = [];
  globalThis.fetch = vi.fn(async () => ({
    ok: true,
    blob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])]),
  })) as never;
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:probe");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.stubGlobal(
    "Image",
    class {
      naturalWidth = width;
      naturalHeight = height;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) {
        decoded.push(this as unknown as HTMLImageElement);
      }
    },
  );

  //: 查询用 `screen`(弹窗是 portal,挂在 `<body>` 上)**而不是容器**:画布的 `aria-label` 是
  //: 「蒙版画布」,而右栏那把工具分段里也有一项叫这个名字(`maskBrush` 与 `maskCanvasLabel` 同文案)
  //: —— 按名字查会先摸到那颗 `<button>`。先找画布,再从它的 `closest('[role="dialog"]')` 里查其余控件。
  const dialog = () => {
    const found = view().closest('[role="dialog"]');
    if (!found) throw new Error("画布不在弹窗里");
    return within(found as HTMLElement);
  };
  const view_ = () => screen.getByLabelText("蒙版画布", { selector: "canvas" }) as HTMLCanvasElement;
  const view = view_;
  /** 可见画布那个 2D 上下文(它上面记着"这一帧被要求画了什么")。 */
  const viewContext = () => pixelOf(view()).getContext("2d") as unknown as { calls: string[] };
  const mask = () => {
    //: 蒙版那张**不在 DOM 里**、尺寸等于文档,而且组件自己登记过(见 MaskEditor 的 isMaskCanvas)——
    //: 只按尺寸找会摸到派生层那张临时画布(它同样大小,但装的是蒙版的着色派生)。
    const candidates = canvasesOfSize(width, height).filter((one) => one !== view() && !one.isConnected);
    const found = candidates.find((one) => isMaskCanvas(one)) ?? candidates[candidates.length - 1];
    if (!found) throw new Error("没有离屏蒙版那张画布");
    return found;
  };

  return {
    underlay,
    images: decoded,
    source: sourceElement,
    view,
    viewPixels: () => pixelOf(view()),
    mask,
    maskPixels: () => pixelOf(mask()),
    viewCalls: () => {
      //: `drawMaskView` 每一帧第一件事就是清整张 ⇒ "最后一个 `clearRect` 之后的那一段"正好是
      //: 一帧的层表在屏幕上的样子。
      const calls = viewContext().calls;
      let start = calls.length;
      while (start > 0 && calls[start - 1] !== "clearRect") start -= 1;
      return calls.slice(Math.max(0, start - 1));
    },
    settle: async () => {
      for (let i = 0; i < 4; i += 1) await Promise.resolve();
    },
    ready: () => !(dialog().getByRole("button", { name: "按亮度初始化" }) as HTMLButtonElement).disabled,
    scope: dialog,
    sample(canvas, x, y) {
      const pixels = pixelOf(canvas);
      const at = (y * pixels.width + x) * 4;
      return [...pixels.pixels.data.slice(at, at + 4)];
    },
    mount() {
      const onOpenChange = vi.fn();
      const onDone = vi.fn();
      const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
      render(
        <QueryClientProvider client={client}>
          <PreferencesProvider>
            <MaskEditor open onOpenChange={onOpenChange} workspaceId="w1" source={{ assetId: "src-1", name: "probe.png" }} onDone={onDone} />
          </PreferencesProvider>
        </QueryClientProvider>,
      );
      return { onOpenChange, onDone };
    },
  };
}

/** 让底图"解码完",并等文档换成底图那个尺寸(`按亮度初始化` 可用就是信号)。 */
export async function loadUnderlay(harness: PixelHarness): Promise<void> {
  await waitFor(() => expect(harness.images.length).toBeGreaterThan(0));
  for (const image of harness.images) registerPixelImage(image, harness.underlay);
  registerPixelImage(harness.source, harness.underlay);
  for (const image of harness.images) image.onload?.(new Event("load"));
  //: 底图读完 = 那两个初始化键启用(组件就是这样表态的)。
  await waitFor(() => expect(harness.ready()).toBe(true));
}
