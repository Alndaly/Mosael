/** @vitest-environment jsdom */
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetCanvases, installPixelCanvas, canvasesOfSize } from "@/test/pixelCanvasSetup";
import { loadUnderlay, pixelHarness, type PixelHarness } from "@/test/maskEditorPixels";
import { isMaskCanvas } from "@/components/generation/MaskEditor";

/**
 * ## 维护者复现:「画圆形 / 方形、撤销、反选、撤销反选都会让底图变灰」+「打开瞬间尺寸不对(1024 占位)」
 *
 * 此前的像素级用例盒子和文档一样大(1:1、无缩放),而维护者那边盒子和文档**几乎从不一样大**
 * (竖幅 1624×2880 进不满屏的对话框),合成里底图与蒙版都要过重采样。这一座把盒子换成
 * **另一个尺寸**,断言照旧:没画过的那一格在可见画布上仍然是原图(不是灰的)。
 *
 * 坐标换算不再能"文档 = 屏幕":笔落哪、从可见画布哪一格取样,都走**文档边框那个 div**
 * (它跟着相机走、style 里就是文档左上角 + 缩放)—— 和组件自己是同一个坐标系。
 */

/** 文档 96×120(≠ 打开时那张 1024² 的占位文档);盒子 200×150(≠ 文档 ⇒ 合成带缩放)。 */
const W = 96;
const H = 120;
const BOX = { width: 200, height: 150 };

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

async function open(): Promise<PixelHarness> {
  const harness = pixelHarness({ width: W, height: H, box: BOX });
  harness.mount();
  await waitFor(() => expect(harness.view()).toBeTruthy());
  await loadUnderlay(harness);
  return harness;
}

/** 让 React 把这一下事件处理里的 setState 冲掉(见 MaskEditor.pixels.dom.test.tsx 的 flush)。 */
const flush = async () => {
  await act(async () => undefined);
};

/**
 * 文档坐标 → 屏幕坐标:读**文档边框那个 div**(translate + 宽高,都是 CSS 像素)——
 * 它就是相机写出来的那个映射,测试不去复刻第二份相机数学。
 */
function docToScreen(x: number, y: number): { clientX: number; clientY: number } {
  const frame = document.querySelector<HTMLElement>("[data-mask-doc-frame]")!;
  const match = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(frame.style.transform);
  if (!match) throw new Error("文档边框没有相机变换");
  const scale = Number.parseFloat(frame.style.width) / W;
  return { clientX: Number(match[1]) + (x + 0.5) * scale, clientY: Number(match[2]) + (y + 0.5) * scale };
}

/** 拖一笔(矩形 / 椭圆):按下 → 移动 → 松手,文档坐标给,中间让 React 各冲一次。 */
async function drag(harness: PixelHarness, from: [number, number], to: [number, number]) {
  const view = harness.view();
  fireEvent.pointerDown(view, { ...docToScreen(...from), pointerId: 1, button: 0, buttons: 1 });
  await flush();
  fireEvent.pointerMove(view, { ...docToScreen(...to), pointerId: 1, button: 0, buttons: 1 });
  await flush();
  fireEvent.pointerUp(view, { ...docToScreen(...to), pointerId: 1, button: 0, buttons: 0 });
  await flush();
}

async function press(harness: PixelHarness, name: string) {
  fireEvent.click(harness.scope().getByRole("button", { name }));
  await flush();
}

async function pick(harness: PixelHarness, name: string) {
  const button = harness.scope().getByRole("button", { name });
  fireEvent.click(button);
  await flush();
  expect(button.getAttribute("aria-pressed")).toBe("true");
}

/**
 * 把「笔刷硬度」推到 100%(硬边)。
 *
 * 硬度管的是**每一笔的边缘过渡**:默认 90% 的方框边上有一条 `半径 × (1 − 0.9)` 宽的软边,
 * 反选之后形状之内那一条边不是整块 0,而是一段 `0 → 255` 的斜坡(软边翻过来了)——
 * "形状内逐字节等于原图"那条断言会在边缘那几格上差一点点。这条用例测的是**反选与合成**
 * (别把底图糊成灰),不是软边本身,所以它要的是一个**边缘一刀切、内部满浓度**的形状
 * (浓度来自「不透明度」,默认就是 100%)。
 */
async function hardEdge(harness: PixelHarness) {
  //: 按**那一行的名字**认(hardness / opacity / threshold 都是 0..1,按范围认会认错人)。
  const row = harness.scope().getByText("笔刷硬度", { selector: "span" }).closest("label") as HTMLElement;
  const slider = row.querySelector('[role="slider"]') as HTMLElement;
  slider.focus();
  for (let i = 0; i < 20; i += 1) fireEvent.keyDown(slider, { key: "ArrowRight", bubbles: true, cancelable: true });
  await flush();
  expect(slider.getAttribute("aria-valuenow")).toBe("1");
}

/** 可见画布上对应某个**文档坐标**的那一格(dpr=1:位图 = CSS 盒子,一格对一个 CSS 像素)。 */
function viewAtDoc(harness: PixelHarness, x: number, y: number): number[] {
  const { clientX, clientY } = docToScreen(x, y);
  return harness.sample(harness.view(), Math.floor(clientX), Math.floor(clientY));
}

/** 底图上某个文档坐标的原样 RGB。 */
function original(harness: PixelHarness, x: number, y: number): number[] {
  const at = (y * W + x) * 4;
  return [...harness.underlay.data.slice(at, at + 3)];
}

/** 「没画过的地方不是灰的」:三个角落的 RGB 逐字节等于原图(合成里 multiply 遇白反相是不动底色的)。 */
function expectUnderlayIntact(harness: PixelHarness, where: string) {
  for (const [x, y] of [
    [2, 2],
    [W - 3, H - 3],
    [2, H - 3],
  ] as const) {
    expect(viewAtDoc(harness, x, y).slice(0, 3), `${where}:文档 ${x},${y} 必须仍是原图(不是灰的)`).toEqual(
      original(harness, x, y),
    );
  }
}

/** 「画过的地方确实变了」——否则"没变灰"是空转的绿。 */
function expectPaintedVisible(harness: PixelHarness, x: number, y: number, where: string) {
  expect(viewAtDoc(harness, x, y).slice(0, 3), `${where}:形状中心必须是要改的样子`).not.toEqual(original(harness, x, y));
}

describe("维护者复现:画形状 / 撤销 / 反选不把底图整灰(盒子 ≠ 文档,合成带缩放)", () => {
  it("画圆形(椭圆工具):底图区域仍是原像素,不是灰的", async () => {
    const harness = await open();
    await pick(harness, "椭圆");
    await drag(harness, [20, 20], [60, 70]);
    await harness.settle();

    expectPaintedVisible(harness, 40, 45, "画圆之后");
    expectUnderlayIntact(harness, "画圆之后");
  });

  it("画方形(矩形工具):底图区域仍是原像素,不是灰的", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    await drag(harness, [20, 20], [60, 70]);
    await harness.settle();

    expectPaintedVisible(harness, 40, 40, "画方之后");
    expectUnderlayIntact(harness, "画方之后");
  });

  it("撤销那一笔:底图区域仍是原像素,不是灰的", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    await drag(harness, [20, 20], [60, 70]);
    await press(harness, "撤销");
    await harness.settle();

    expectUnderlayIntact(harness, "撤销之后");
  });

  it("反选:形状之内回到原图,形状之外是「要改」的样子 —— 但没有一处被糊成统一的灰", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    //: 硬边 + 满浓度(不透明度默认 100%)的方框:反选之后形状之内才是**纯黑**(= 不改),底图原样透出来。
    await hardEdge(harness);
    await drag(harness, [20, 20], [60, 70]);
    await press(harness, "反选");
    await harness.settle();

    //: 反选后「要改」的是形状**之外**那一整圈:形状外一点必须是"要改的样子"……
    expect(viewAtDoc(harness, 2, 2).slice(0, 3), "反选后形状外是要改的样子").not.toEqual(original(harness, 2, 2));
    //: ……而形状**之内**的底图必须原样透出来(mask 黑 = 不改)。
    expect(viewAtDoc(harness, 40, 40).slice(0, 3), "反选后形状内是原图").toEqual(original(harness, 40, 40));
    //: 任何一处都不该是"整块同一种灰"(那才是维护者看到的病):三种原色底各取一点,仍各自是彩色。
    for (const [x, y] of [
      [2, 2],
      [W - 3, H - 3],
    ] as const) {
      const seen = viewAtDoc(harness, x, y).slice(0, 3);
      expect(Math.max(...seen) - Math.min(...seen) > 30, `反选后 ${x},${y} 仍是彩色的(不是灰)`).toBe(true);
    }
  });

  it("撤销反选:回到反选前,底图区域仍是原像素,不是灰的", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    await drag(harness, [20, 20], [60, 70]);
    await press(harness, "反选");
    await press(harness, "撤销");
    await harness.settle();

    expectPaintedVisible(harness, 40, 40, "撤销反选之后");
    expectUnderlayIntact(harness, "撤销反选之后");
  });
});

/** 等到「1024² 占位文档已铺上」——打开时那张默认文档在位,底图还没读进来。 */
async function waitDefaultDoc() {
  await waitFor(() =>
    expect(canvasesOfSize(1024, 1024).some((one) => isMaskCanvas(one)), "1024² 占位文档已铺上").toBe(true),
  );
}

describe("维护者复现:在 1024 占位阶段动笔,底图随后才读进来 —— 也不能把底图整灰", () => {
  it("1024 阶段画矩形 → 底图到达(文档换尺寸)→ 没画过的地方仍是原像素", async () => {
    const harness = pixelHarness({ width: W, height: H, box: BOX });
    harness.mount();
    await waitFor(() => expect(harness.view()).toBeTruthy());
    //: 此刻文档还是打开时那张 1024² 占位(维护者看到的"打开一瞬间尺寸不对"就是这个窗口)。
    await waitDefaultDoc();

    await pick(harness, "矩形");
    await drag(harness, [20, 20], [60, 70]);
    await harness.settle();

    //: 底图到了:文档从 1024² 换成 96×120,按下时那一笔按新尺寸被 carry 过来。
    await loadUnderlay(harness);

    //: 没画过的地方必须仍是原图 —— 维护者的"变灰"就是这一步之后整块发灰。
    expectUnderlayIntact(harness, "底图到达之后");
  });

  it("笔拖到一半底图才读进来(文档当场换尺寸)→ 松手之后没画过的地方仍是原像素", async () => {
    const harness = pixelHarness({ width: W, height: H, box: BOX });
    harness.mount();
    await waitFor(() => expect(harness.view()).toBeTruthy());
    await waitDefaultDoc();

    //: 按下(1024² 文档)→ 底图到达 → 移动 → 松手:整个拖动横跨那次换尺寸。
    await pick(harness, "矩形");
    const view = harness.view();
    fireEvent.pointerDown(view, { ...docToScreen(20, 20), pointerId: 1, button: 0, buttons: 1 });
    await flush();
    await loadUnderlay(harness);
    //: 文档已经换成 96×120,相机**当场**重适应这一档(translate(40px) 宽 120px)——不许停在
    //: 1024² 那一档:否则松手前整张图都按旧尺寸摆(图错位、四周露出画布灰底,"底图变灰")。
    const frame = () => document.querySelector<HTMLElement>("[data-mask-doc-frame]")!;
    expect(frame().style.transform, "换尺寸当场重适应").toBe("translate(40px, 0px)");
    expect(frame().style.width, "新文档的适应窗口").toBe("120px");
    fireEvent.pointerMove(view, { ...docToScreen(60, 70), pointerId: 1, button: 0, buttons: 1 });
    await flush();
    fireEvent.pointerUp(view, { ...docToScreen(60, 70), pointerId: 1, button: 0, buttons: 0 });
    await flush();
    await harness.settle();

    expectPaintedVisible(harness, 40, 40, "跨尺寸拖动之后");
    expectUnderlayIntact(harness, "跨尺寸拖动之后");
  });
});

describe("维护者复现:打开瞬间尺寸不拿 1024 占位谎称已确立", () => {
  it("底图还没读进来时,底栏显示「—」而非 1024 占位;确立后显示真实尺寸", async () => {
    const harness = pixelHarness({ width: W, height: H, box: BOX });
    harness.mount();
    await waitFor(() => expect(harness.view()).toBeTruthy());

    //: 底图还在路上 —— 此刻输出尺寸还不存在(出口会按源图缩回),拿一个假数字谎称"已确立"
    //: 正是维护者看到的"打开一瞬间尺寸不对"。
    await waitDefaultDoc();
    expect(harness.scope().queryByText("1024 × 1024 px"), "底图读入前不许把 1024 占位当已确立尺寸报出来").toBeNull();
    expect(harness.scope().queryByText("—"), "读出来之前那一格是待定,不是占位数字").not.toBeNull();

    await loadUnderlay(harness);
    await waitFor(() => expect(harness.scope().queryByText(`${W} × ${H} px`)).not.toBeNull());
  });
});
