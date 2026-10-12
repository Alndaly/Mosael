/** @vitest-environment jsdom */
import { PixelCanvas, PixelContext2D, registerCanvasLookup } from "@/test/pixelCanvas";

/**
 * 把 jsdom 的平台替身装成"真有像素"的那一份(见 `pixelCanvas`),并**把每张画布的像素登记下来**
 * —— 测试要回头读"可见那张""离屏那张"到底画成了什么样。
 *
 * 装的只有两样:
 *
 * - `getContext("2d")` → `PixelContext2D`(真的按规范算 `source-over` / `difference` /
 *   `multiply` / `lighter` + `globalAlpha`);
 * - `width` / `height` 一改就换一张清空的位图(浏览器语义 —— "重铺文档"那一趟测的就是它)。
 *
 * 每个测试文件 `beforeAll` 调一次:jsdom 的 `HTMLCanvasElement` 是全局的,而 vitest 一个文件一个环境。
 */

/** 本文件里建过的每一张画布 → 它的像素。 */
const registry = new Map<HTMLCanvasElement, PixelCanvas>();
let installed = false;

/** 某张画布的像素(没建过就先建一张空的,尺寸按元素现在的大小)。 */
export function pixelOf(element: HTMLCanvasElement): PixelCanvas {
  let found = registry.get(element);
  if (!found) {
    found = new PixelCanvas(element.width, element.height, new WeakMap(), element);
    registry.set(element, found);
  }
  return found;
}

/** 按尺寸找画布 —— 蒙版那张不在 DOM 里,只能这么找。 */
export function canvasesOfSize(width: number, height: number): HTMLCanvasElement[] {
  return [...registry.entries()].filter(([element]) => element.width === width && element.height === height).map(([element]) => element);
}

/** 忘了上一批画布(每条用例开头清一次,别把上一条的像素带过来)。 */
export function forgetCanvases(): void {
  registry.clear();
}

/** jsdom 没有 `ImageData`(组件里 `createImageData` / `getImageData` 都要它)。 */
class ImageDataPolyfill {
  readonly data: Uint8ClampedArray;
  readonly width: number;
  readonly height: number;
  readonly colorSpace: PredefinedColorSpace = "srgb";
  constructor(width: number, height: number) {
    this.width = width;
    this.height = height;
    this.data = new Uint8ClampedArray(width * height * 4);
  }
}

export function installPixelCanvas(): void {
  if (installed) return;
  installed = true;
  globalThis.ImageData ??= ImageDataPolyfill as unknown as typeof ImageData;
  //: `drawImage(某一个 canvas 元素)` 要能查到它的像素 —— 这条路只认注册表。
  registerCanvasLookup((element) => pixelOf(element).pixels);

  //: 上下文挂在**那张 PixelCanvas** 上(`pixelOf(element).getContext("2d")` 拿到的就是它)——
  //: 不能再放一张以元素为键的表里:`pixelOf` 每次可能给出不同的 `PixelCanvas` 实例,
  //: 两张表各说各话时,组件画的上下文和测试读的上下文就不是同一个对象了。
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement, kind: string) {
    if (kind !== "2d") return null;
    return pixelOf(this).getContext("2d");
  } as unknown as typeof HTMLCanvasElement.prototype.getContext;

  for (const axis of ["width", "height"] as const) {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, axis);
    Object.defineProperty(HTMLCanvasElement.prototype, axis, {
      configurable: true,
      get(this: HTMLCanvasElement) {
        return descriptor?.get?.call(this);
      },
      set(this: HTMLCanvasElement, value: number) {
        descriptor?.set?.call(this, value);
        //: 位图换一张(上下文**不**重建 —— 浏览器里老 ctx 照旧可用,读出来的是新位图)。
        //: 那几条断言"被调用过什么"的用例靠的就是同一个 ctx 上累积的 calls。
        pixelOf(this).resize(this.width, this.height);
      },
    });
  }
}

export { PixelCanvas, PixelContext2D };
