/** @vitest-environment jsdom */
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/domains/assets", () => ({
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  savePaintedMask: vi.fn(),
}));

import { savePaintedMask, type Asset } from "@/api/domains/assets";
import { PixelImage } from "@/test/pixelCanvas";
import { forgetCanvases, installPixelCanvas } from "@/test/pixelCanvasSetup";
import { loadImages, pixelHarness, type PixelHarness } from "@/test/maskEditorPixels";

/**
 * ## 维护者拍板:蒙版槽里传进来一张**彩色图**时,它是**参考底图**,不是底稿
 *
 * 「蒙版」那一格的 `accept` 是 `image/*`(`lib/sourceFrames.ts` 的 `mask`),用户**能**把一张彩色照片
 * 传进去。此前那张图一律当**底稿**(`initial`)`paste` 进蒙版:`paste` 是蒙版唯一的 `drawImage`
 * (源图什么色照抄什么色),于是颜色进了蒙版画布、屏幕上显示成它的灰度 —— 维护者要的是"传进来的
 * 彩色照片就**看着是彩色**的,蒙版从空白开始画"(上一轮那条 `normalizeGray` 只是把颜色拦在契约外,
 * 没解决"我看到的是彩色"这件事)。
 *
 * 现在按**它是灰还是彩**分两条路(`MaskEditor` 的 `isGrayscaleImage`,容差 2):
 *
 * | 蒙版槽里那张图 | 当什么 | 蒙版画布 | 屏幕 |
 * | --- | --- | --- | --- |
 * | 灰度(每个像素 r ≈ g ≈ b,差 ≤ 2)| **已有的蒙版**(底稿) | 铺进去,接着画 | 那张图 |
 * | 彩色(有像素差 > 2)| **参考底图**(和 `source` 一个槽位) | 空白黑底 | **原始彩色** |
 *
 * 优先级:`source`(参考图 / 首帧那一格)在的时候它就是底图 —— 彩色 initial 不抢,只被忽略成底稿。
 *
 * **存回去的仍然是灰度蒙版**(契约没变:导出 `writer().canvas()`,每个像素 `r = g = b`、不透明)。
 * `paste` 里那条 `normalizeGray` 保留着当兜底 —— 容差之内的近灰图仍会当底稿铺进蒙版,归一那一下
 * 就是它兜的(见下面那条"差 ≤ 2"的用例)。
 */

const W = 96;
const H = 40;
/** 三竖条:纯绿 / 纯蓝 / 纯红 —— 维护者传进蒙版槽的那种照片。 */
const GREEN = [0, 255, 0] as const;
const BLUE = [0, 0, 255] as const;
const RED = [255, 0, 0] as const;

/** Rec.601(`maskPixels` 的 `gray`,也是 `normalizeGray` / 后端 `L` 模式走的那条)。 */
const luma = ([r, g, b]: readonly [number, number, number]) => Math.floor(0.299 * r + 0.587 * g + 0.114 * b + 0.5);

/** 一张**彩色**照片(蒙版槽里的那一张):绿 / 蓝 / 红三竖条。 */
function colorPhoto(width: number, height: number): PixelImage {
  const image = new PixelImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const column = x < width / 3 ? GREEN : x < (width * 2) / 3 ? BLUE : RED;
      image.data.set([...column, 255], (y * width + x) * 4);
    }
  }
  return image;
}

/** 一张**真的蒙版**(正常那一档):左右各一半黑与白,逐像素 `r = g = b`。 */
function grayMask(width: number, height: number): PixelImage {
  const image = new PixelImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = x < width / 2 ? 0 : 255;
      image.data.set([value, value, value, 255], (y * width + x) * 4);
    }
  }
  return image;
}

/** 一整张同色 —— 判灰度那条容差的边界就靠它(`flat(W, H, [100, 102, 100])` 这种)。 */
function flat(width: number, height: number, [r, g, b]: readonly [number, number, number]): PixelImage {
  const image = new PixelImage(width, height);
  for (let at = 0; at < image.data.length; at += 4) image.data.set([r, g, b, 255], at);
  return image;
}

/** 三竖条各自的取样点(**文档坐标**;盒子 = 文档、dpr = 1 ⇒ 与位图坐标一致)。 */
const COLUMN_X = { green: Math.floor(W / 6), blue: Math.floor(W / 2), red: Math.floor((W * 5) / 6) };
const SAMPLE_Y = Math.floor(H / 2);

/** 被 `toBlob` 导出的那张画布(见「存回」那条:它必须是离屏蒙版那张)。 */
let exported: HTMLCanvasElement | null = null;

beforeAll(() => {
  installPixelCanvas();
  //: jsdom 没有真的 `toBlob`(它要一张真位图)。这里只记下**是哪张画布**被交出去,再给一个真 Blob
  //: —— 导出这条路本身(是不是离屏蒙版那张、像素是不是灰的)因此测得到。
  HTMLCanvasElement.prototype.toBlob = function toBlob(this: HTMLCanvasElement, callback: BlobCallback, type?: string) {
    exported = this;
    callback(new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: type ?? "image/png" }));
  } as unknown as typeof HTMLCanvasElement.prototype.toBlob;
});

beforeEach(() => {
  forgetCanvases();
  exported = null;
  vi.mocked(savePaintedMask).mockReset();
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

/** 画布上某个**文档坐标**的那一格。 */
const pixelAt = (harness: PixelHarness, canvas: HTMLCanvasElement, x: number, y: number) => harness.sample(canvas, x, y);

/** 蒙版是不是**一片空白**(黑底、不透明)—— "蒙版从空白开始画"那一条。 */
function expectBlankMask(harness: PixelHarness) {
  const pixels = harness.maskPixels().pixels.data;
  let stray = -1;
  for (let at = 0; at < pixels.length; at += 4) {
    if (pixels[at] !== 0 || pixels[at + 1] !== 0 || pixels[at + 2] !== 0 || pixels[at + 3] !== 255) {
      stray = at >> 2;
      break;
    }
  }
  const at = stray * 4;
  expect(
    stray,
    `蒙版第 ${stray} 个像素是 [${pixels[at]}, ${pixels[at + 1]}, ${pixels[at + 2]}, ${pixels[at + 3]}] —— 彩色 initial 不许铺进蒙版,这里要从空白(黑底)开始`,
  ).toBe(-1);
}

/** 打开一座:蒙版槽里放 `slot`,`hasSource` 决定参考图那一格有没有图。 */
async function open(slot: PixelImage, hasSource: boolean): Promise<PixelHarness> {
  const harness = pixelHarness({ width: W, height: H, initial: slot, hasSource });
  harness.mount();
  await waitFor(() => expect(harness.view()).toBeTruthy());
  await loadImages(harness);
  await harness.settle();
  return harness;
}

describe("蒙版槽里的彩色图 = 参考底图(蒙版从空白开始)", () => {
  it("有参考图时:参考图仍是底图 —— 那张照片既不进蒙版,也不抢底图", async () => {
    const harness = await open(colorPhoto(W, H), true);

    //: 底图还是 `source` 那一格(`buildUnderlay`:左 2/3 蓝、右 1/3 红),原样画在屏幕上。
    expect(pixelAt(harness, harness.view(), COLUMN_X.green, SAMPLE_Y), "彩色 initial 抢了底图").toEqual([0, 0, 255, 255]);
    expect(pixelAt(harness, harness.view(), COLUMN_X.red, SAMPLE_Y)).toEqual([255, 0, 0, 255]);

    //: 蒙版是**空白**:那条绿竖条(以及整张)一个像素都没进蒙版。
    expectBlankMask(harness);
  });

  it("没有参考图时:那张照片当底图,屏幕上是**原始彩色**(不是它的灰度)", async () => {
    const harness = await open(colorPhoto(W, H), false);

    //: 屏幕上是彩色照片本身:纯绿 / 纯蓝 / 纯红。灰的话这里会是 luma 那一档(`luma(GREEN)`=149)。
    expect(pixelAt(harness, harness.view(), COLUMN_X.green, SAMPLE_Y), "绿色那一竖条必须是原始彩色").toEqual([...GREEN, 255]);
    expect(pixelAt(harness, harness.view(), COLUMN_X.blue, SAMPLE_Y)).toEqual([...BLUE, 255]);
    expect(pixelAt(harness, harness.view(), COLUMN_X.red, SAMPLE_Y)).toEqual([...RED, 255]);

    //: 它走的是**底图**那条路:「按亮度初始化」这类从底图起手的键因此是可用的(和 `source` 一样)。
    expect(harness.scope().getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(false);

    //: 而蒙版从空白开始。
    expectBlankMask(harness);
  });

  it("灰度 initial:一个字都没变 —— 仍当底稿铺进蒙版(不是底图)", async () => {
    const draft = grayMask(W, H);
    const harness = await open(draft, false);

    //: 蒙版逐字节等于那张底稿 —— 继续在已有的蒙版上画。
    expect([...harness.maskPixels().pixels.data]).toEqual([...draft.data]);
    //: 可见那张上没有"底图"那一层(层表第一条分支):屏幕上显示的就是蒙版自己。
    expect(pixelAt(harness, harness.view(), Math.floor(W / 4), SAMPLE_Y)).toEqual([0, 0, 0, 255]);
    expect(pixelAt(harness, harness.view(), Math.floor((W * 3) / 4), SAMPLE_Y)).toEqual([255, 255, 255, 255]);
    //: 它没有被当成底图:「从底图起手」那两个键照旧禁用。
    expect(harness.scope().getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(true);
  });

  it("判灰度那条容差:每通道差 ≤ 2 的还算灰 —— 当底稿铺进蒙版,并由 paste 归一成 Rec.601 亮度", async () => {
    //: 灰度 JPEG 解码后各通道会差个 1 —— 这种"近灰"必须照旧当**已有的蒙版**,不能当彩色照片丢掉。
    const near = flat(W, H, [100, 102, 100]);
    const harness = await open(near, false);

    //: 铺进去了(不是空白),而且是灰的:100 / 102 / 100 → 101(Rec.601 四舍五入)。
    expect(pixelAt(harness, harness.mask(), Math.floor(W / 2), SAMPLE_Y)).toEqual([luma([100, 102, 100]), luma([100, 102, 100]), luma([100, 102, 100]), 255]);
    expect(luma([100, 102, 100])).toBe(101);
  });

  it("判灰度那条容差:差 3 就算彩色 —— 当参考底图,蒙版保持空白", async () => {
    const odd = flat(W, H, [100, 103, 100]);
    const harness = await open(odd, false);

    //: 屏幕上原样是那张图(它当了底图)……
    expect(pixelAt(harness, harness.view(), Math.floor(W / 2), SAMPLE_Y)).toEqual([100, 103, 100, 255]);
    //: ……而蒙版是空白的:差 3 就够把它判成"彩色照片"了。
    expectBlankMask(harness);
  });

  it("彩色 initial(有参考图):反选 + 撤销一趟快照往返之后蒙版仍是空白 —— 底稿那条路整个没走", async () => {
    const harness = await open(colorPhoto(W, H), true);
    const before = [...harness.maskPixels().pixels.data];

    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expect([...harness.maskPixels().pixels.data]).toEqual(before);
    expectBlankMask(harness);
    //: 底图那一层不受蒙版动作影响,还是 `source`。
    expect(pixelAt(harness, harness.view(), COLUMN_X.green, SAMPLE_Y)).toEqual([0, 0, 255, 255]);
  });

  it("灰度 initial:反选 + 撤销一趟快照往返之后逐字节不变(这一档不许被改到)", async () => {
    const draft = grayMask(W, H);
    const harness = await open(draft, false);
    const before = [...harness.maskPixels().pixels.data];

    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expect([...harness.maskPixels().pixels.data]).toEqual(before);
  });

  it("存回:彩色 initial 打开、反选之后存下去的仍是**灰度蒙版**(不是那张照片)", async () => {
    vi.mocked(savePaintedMask).mockResolvedValue({ id: "mask-9", name: "蒙版 · probe.png" } as Asset);
    const harness = await open(colorPhoto(W, H), true);

    //: 反选 = 蒙版整张变白(空白黑底的反相)—— 一次真实的编辑,存下去的该是它。
    await press(harness, "反选");
    await press(harness, "存成蒙版");
    await waitFor(() => expect(savePaintedMask).toHaveBeenCalledTimes(1));

    //: 交上去的就是离屏那张蒙版(底图只画在可见那张上,永远不进导出)。
    expect(exported).toBe(harness.mask());
    const pixels = harness.maskPixels().pixels.data;
    let colored = -1;
    for (let at = 0; at < pixels.length; at += 4) {
      if (pixels[at] !== pixels[at + 1] || pixels[at + 1] !== pixels[at + 2] || pixels[at + 3] !== 255) {
        colored = at >> 2;
        break;
      }
    }
    expect(colored, "导出的蒙版必须逐像素 r = g = b 且不透明(灰度契约)").toBe(-1);
    //: 而它确实不是那张彩色照片(照片那条绿竖条在这里是白,不是绿)。
    expect(pixelAt(harness, harness.mask(), COLUMN_X.green, SAMPLE_Y)).toEqual([255, 255, 255, 255]);
  });
});
