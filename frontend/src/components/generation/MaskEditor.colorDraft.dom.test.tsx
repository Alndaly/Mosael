/** @vitest-environment jsdom */
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { PixelImage } from "@/test/pixelCanvas";
import { forgetCanvases, installPixelCanvas } from "@/test/pixelCanvasSetup";
import { loadImages, pixelHarness, type PixelHarness } from "@/test/maskEditorPixels";

/**
 * ## 维护者复现:打开的是一张**彩色照片**,画了形状 / 撤销 / 反选之后整幅变成黑白
 *
 * 真浏览器里逐像素跑过一遍(`MaskEditor` + `maskPixels` + `maskCamera` 全是真的,headless
 * Chromium 153),现象与那几张截图对得上:底稿(打开时已经有的那张蒙版)只要是**彩色**的,
 * 打开时屏幕上就是那张彩色照片;而第一次走过 `snapshot` / `restore`(撤销、形状的每一帧预览、
 * 反选、应用边缘)之后,整张**忽然变成红通道那一份灰度** —— 也就是"整幅黑白"。
 *
 * 根因不在合成(`drawMaskView` / `maskLayer`,真浏览器里逐字节是对的),也不在"写到了别的画布"
 * (`putImageData` 的每一次都落在蒙版那张上,调用栈逐条核对过):在 `MaskContext.paste` ——
 * 它用 `drawImage` **照抄**源图,源图是彩色的,颜色就这么进了蒙版画布;而蒙版的契约是
 * **逐像素 `r = g = b`**。`snapshot()` 存的是单通道(`grayscaleOf` 取红通道),`restore()` 再用
 * `writeGrayscale` 写回 `r = g = b` —— 于是第一次往返就把彩色换成红通道那份灰度。
 *
 * 画笔/橡皮**不走**这条路(`stroke` 只往上画白/黑),所以它们看着"没事" —— 维护者报的分叉点正是它。
 *
 * 下面这一座把 `paste` 那条路整条走真:底稿是一张**真彩色**的图(`drawImage` 照抄颜色),
 * 合成由 `src/test/pixelCanvas` 那份会算像素的替身按规范算(`source-over` / `multiply` /
 * `lighter` + `globalAlpha`),断言打在**蒙版画布**与**可见画布**的像素上。
 */

const W = 96;
const H = 40;
/** 三竖条:纯绿 / 纯蓝 / 纯红。红通道与 Rec.601 亮度差得很远,"换成红通道"一眼看得出。 */
const GREEN = [0, 255, 0] as const;
const BLUE = [0, 0, 255] as const;
const RED = [255, 0, 0] as const;

/** Rec.601(`maskPixels` 的 `gray`,也是后端归一成 `L` 模式走的那条)。 */
const luma = ([r, g, b]: readonly [number, number, number]) => Math.floor(0.299 * r + 0.587 * g + 0.114 * b + 0.5);

/** 一张**彩色**的底稿:维护者往蒙版槽里传进去的那张照片。 */
function colorDraft(width: number, height: number): PixelImage {
  const image = new PixelImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const column = x < width / 3 ? GREEN : x < (width * 2) / 3 ? BLUE : RED;
      image.data.set([...column, 255], (y * width + x) * 4);
    }
  }
  return image;
}

/** 一张**本来是灰**的底稿(正常那一档):左右各一半黑与白。 */
function grayDraft(width: number, height: number): PixelImage {
  const image = new PixelImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = x < width / 2 ? 0 : 255;
      image.data.set([value, value, value, 255], (y * width + x) * 4);
    }
  }
  return image;
}

/** 三竖条各自的取样点(**文档坐标**;盒子 = 文档、dpr = 1 ⇒ 与位图坐标一致)。 */
const COLUMN_X = { green: Math.floor(W / 6), blue: Math.floor(W / 2), red: Math.floor((W * 5) / 6) };
const SAMPLE_Y = Math.floor(H / 2);

beforeAll(() => {
  installPixelCanvas();
});

beforeEach(() => {
  forgetCanvases();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const flush = async () => {
  await act(async () => undefined);
};

async function press(harness: PixelHarness, name: string) {
  fireEvent.click(harness.scope().getByRole("button", { name }));
  await flush();
}

/** 画布上某个**文档坐标**的那一格(盒子 = 文档 ⇒ 1:1)。 */
const pixelAt = (harness: PixelHarness, canvas: HTMLCanvasElement, x: number, y: number) => harness.sample(canvas, x, y);

/** 蒙版画布上那一格是不是**灰**的(`r = g = b`、不透明)—— 蒙版契约那一条。 */
function grayThere(harness: PixelHarness, x: number, y: number): [number, number, number, number] {
  const [r, g, b, a] = pixelAt(harness, harness.mask(), x, y);
  expect(a, `蒙版在文档 ${x},${y} 必须不透明`).toBe(255);
  expect([r, g, b], `蒙版在文档 ${x},${y} 必须是灰的(r = g = b)`).toEqual([r, r, r]);
  return [r, g, b, a];
}

/** 打开一座:底稿是 `draft`,`hasSource` 决定可见那张上有没有底图。 */
async function open(draft: PixelImage, hasSource: boolean): Promise<PixelHarness> {
  const harness = pixelHarness({ width: W, height: H, initial: draft, hasSource });
  harness.mount();
  await waitFor(() => expect(harness.view()).toBeTruthy());
  await loadImages(harness);
  await harness.settle();
  return harness;
}

describe("维护者复现:彩色底稿进蒙版之后,第一次快照往返把它变成红通道的灰度", () => {
  it("打开:蒙版里每一个像素就已经是灰的(彩色的底稿当场归一,不是照抄进去)", async () => {
    const harness = await open(colorDraft(W, H), true);
    const pixels = harness.maskPixels().pixels.data;

    let colored = -1;
    for (let at = 0; at < pixels.length; at += 4) {
      if (pixels[at] !== pixels[at + 1] || pixels[at + 1] !== pixels[at + 2]) {
        colored = at >> 2;
        break;
      }
    }
    expect(
      colored,
      `蒙版第 ${colored} 个像素是彩色的([${pixels[colored * 4]}, ${pixels[colored * 4 + 1]}, ${pixels[colored * 4 + 2]}])` +
        " —— 蒙版契约是灰度图(r = g = b),彩色留在这里,下一次 snapshot/restore 就会把它换成红通道那一份",
    ).toBe(-1);

    //: 归一按 **Rec.601 亮度**(和 `thresholdMask`、后端 `L` 模式同一条),不是红通道。
    expect(grayThere(harness, COLUMN_X.green, SAMPLE_Y)).toEqual([luma(GREEN), luma(GREEN), luma(GREEN), 255]);
    expect(grayThere(harness, COLUMN_X.blue, SAMPLE_Y)).toEqual([luma(BLUE), luma(BLUE), luma(BLUE), 255]);
    expect(grayThere(harness, COLUMN_X.red, SAMPLE_Y)).toEqual([luma(RED), luma(RED), luma(RED), 255]);
  });

  it("反选 + 撤销(一趟快照往返):蒙版还是同一张图,没有被换成红通道那一份", async () => {
    const harness = await open(colorDraft(W, H), true);
    const before = [...harness.maskPixels().pixels.data];

    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expect([...harness.maskPixels().pixels.data]).toEqual(before);
  });

  it("屏幕上(没有底图,可见那张就是蒙版):彩色照片走一趟往返之后颜色不变,而且是灰的不是红通道的黑", async () => {
    const harness = await open(colorDraft(W, H), false);

    const opened = pixelAt(harness, harness.view(), COLUMN_X.green, SAMPLE_Y);
    expect(opened, "打开时屏幕上那一格是**亮度**灰(Rec.601),不是原图的纯绿、也不是红通道的黑").toEqual([
      luma(GREEN),
      luma(GREEN),
      luma(GREEN),
      255,
    ]);

    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expect(pixelAt(harness, harness.view(), COLUMN_X.green, SAMPLE_Y), "反选 + 撤销之后屏幕上那一格不许变").toEqual(opened);
    expect(pixelAt(harness, harness.view(), COLUMN_X.red, SAMPLE_Y)).toEqual([luma(RED), luma(RED), luma(RED), 255]);
  });

  it("底稿本来就是灰的:一趟快照往返之后照旧逐字节不变(修法不许动正常那一档)", async () => {
    const harness = await open(grayDraft(W, H), false);
    const before = [...harness.maskPixels().pixels.data];

    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expect([...harness.maskPixels().pixels.data]).toEqual(before);
  });
});
