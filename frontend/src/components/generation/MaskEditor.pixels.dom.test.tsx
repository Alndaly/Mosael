/** @vitest-environment jsdom */
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetCanvases, installPixelCanvas, pixelOf, type PixelCanvas } from "@/test/pixelCanvasSetup";
import { loadUnderlay, pixelHarness, type PixelHarness } from "@/test/maskEditorPixels";
import { createMaskWriter } from "@/lib/maskPixels";

/**
 * ## 「蒙版编辑只动蒙版」这条不变量:像素级的那几条回归
 *
 * 维护者报的那一族(清空 / 撤销 / 反选 / 形状 / 橡皮)在屏幕上表现成"底图没了""变成灰白"
 * —— 两条完全不同的成因(蒙版里漏出透明像素 / 底图那一层没画)在**像素上**分得开,而只记账的替身
 * 一条都测不出来。这里用 `src/test/pixelCanvas` 那份真的会算的 2D 替身,把两件事都钉住:
 *
 * 1. **可见画布上没画过的地方逐字节等于原图**(「显示底图」开着时,任何动作之后都成立);
 * 2. **蒙版里每个像素 alpha 都是 255**(契约:灰度、白 = 要改、全不透明)。
 *
 * 底图走组件真实那条路(fetch → blob → `Image` → `drawImage`),所以"底图那一层在不在"也是在
 * 真实的合成里量的。真 Chromium 里的逐像素实测见报告(探针已删)。
 */

/** 底图 = 文档尺寸:不存在 contain 缩放,断言是**逐字节**的。 */
const W = 96;
const H = 120;
/** 左 2/3 纯蓝、右 1/3 纯红 —— 合成出什么一眼分得清。 */
const BLUE = [0, 0, 255, 255];

beforeAll(() => {
  installPixelCanvas();
});

beforeEach(() => {
  //: 这一条用例的画布登记表清空 —— 别把上一条的像素带过来(`pixelOf` 是按对象查的)。
  forgetCanvases();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function open(withUnderlay = true): Promise<PixelHarness> {
  const harness = pixelHarness({ width: W, height: H });
  harness.mount();
  await waitFor(() => expect(harness.view()).toBeTruthy());
  if (withUnderlay) await loadUnderlay(harness);
  return harness;
}

/** 文档坐标 → 屏幕坐标(元素矩形 = jsdom 里给的那个 `box`)。 */
function at(harness: PixelHarness, x: number, y: number) {
  const rect = harness.view().getBoundingClientRect();
  return { clientX: rect.left + (x / W) * rect.width, clientY: rect.top + (y / H) * rect.height };
}

/**
 * 让 React 把这一下的事件处理跑完。
 *
 * **必须跑**:组件在事件处理里 `setState`(选工具 / 开关底图),而 `fireEvent` 不会替你把那一次
 * 渲染冲掉 —— 紧接着发下一个事件时,组件读到的还是**上一个** state(实测:选完「笔刷」立刻按下,
 * `tool` 还是 `brush` 的默认值之外的旧值,于是一笔都没画上去,断言看到的是"空转的绿")。
 */
const flush = async () => {
  //: 同步 `act`:把这一次事件处理里的 setState 冲掉。**不用真计时器**(拿真计时器"等 0 毫秒"是
  //: `design/testsWaitForConditions` 那道棘轮明令只减不增的写法 —— 机器一忙就随机红)。
  await act(async () => undefined);
};

/** 选一种工具:工具条上的一颗按下式按钮(`aria-pressed`)。 */
async function pick(harness: PixelHarness, name: string) {
  const button = harness.scope().getByRole("button", { name });
  fireEvent.click(button);
  await flush();
  expect(button.getAttribute("aria-pressed")).toBe("true");
}

async function press(harness: PixelHarness, name: string) {
  fireEvent.click(harness.scope().getByRole("button", { name }));
  await flush();
}

/**
 * 把「笔刷硬度」推到 100%。
 *
 * 默认 90% 的笔刷是**一串径向渐变** —— 笔迹边缘是中间灰(实测 30 / 89 / 145 这些值),
 * 于是"蒙版那点是 255"这种断言会随机红。推到 100% 走的是实心那一条(`HARD_EDGE`),
 * 笔迹就只有 0 和 255(同一个判据也是那个圈变硬的判据)。
 */
async function hardBrush(harness: PixelHarness) {
  const slider = sliderWith(harness, (one) => one.getAttribute("aria-valuemax") === "1", "硬度");
  slider.focus();
  for (let i = 0; i < 20; i += 1) {
    fireEvent.keyDown(slider, { key: "ArrowRight", bubbles: true, cancelable: true });
  }
  await flush();
  expect(slider.getAttribute("aria-valuenow")).toBe("1");
}

/**
 * 按 `aria-valuemin` / `aria-valuemax` 认一根滑块。
 *
 * radix 的滑块没有 `aria-label`(名字来自外面那个 `<label>`),按 `role="slider"` 的名字查不到 ——
 * 只能按这两口数字认:硬度 0..1、羽化 0..64、扩张 −64..64、笔刷大小 2..400。
 */
function sliderWith(harness: PixelHarness, match: (one: HTMLElement) => boolean, what: string): HTMLElement {
  const found = harness.scope().getAllByRole("slider").find((one: HTMLElement) => match(one)) as HTMLElement | undefined;
  if (!found) throw new Error(`没有找到${what}滑块`);
  return found;
}

/** 一根滑块按 `times` 下方向键(每一档一下)。 */
async function stepSlider(slider: HTMLElement, key: "ArrowRight" | "ArrowLeft", times: number) {
  slider.focus();
  for (let i = 0; i < times; i += 1) fireEvent.keyDown(slider, { key, bubbles: true, cancelable: true });
  await flush();
}

/** 把「羽化」滑块推到 `steps`(它是 0..64 那一根;「扩张」是 −64..64)。 */
async function featherBy(harness: PixelHarness, steps: number) {
  const slider = sliderWith(
    harness,
    (one) => one.getAttribute("aria-valuemax") === "64" && one.getAttribute("aria-valuemin") === "0",
    "羽化",
  );
  await stepSlider(slider, "ArrowRight", steps);
  expect(slider.getAttribute("aria-valuenow")).toBe(String(steps));
}

/** 把「扩张 / 收缩」滑块推到 `target`(−64..64,按当前值算出要按几下)。 */
async function setGrow(harness: PixelHarness, target: number) {
  const slider = sliderWith(harness, (one) => one.getAttribute("aria-valuemin") === "-64", "扩张");
  const from = Number(slider.getAttribute("aria-valuenow"));
  await stepSlider(slider, target >= from ? "ArrowRight" : "ArrowLeft", Math.abs(target - from));
  expect(slider.getAttribute("aria-valuenow")).toBe(String(target));
}

/** 拖一笔:按下 → 移动 → 松手,每一步之间让 React 冲一次。 */
async function drag(harness: PixelHarness, from: [number, number], to: [number, number]) {
  const view = harness.view();
  const start = at(harness, ...from);
  const end = at(harness, ...to);
  fireEvent.pointerDown(view, { ...start, pointerId: 1, button: 0, buttons: 1 });
  await flush();
  fireEvent.pointerMove(view, { ...end, pointerId: 1, button: 0, buttons: 1 });
  await flush();
  fireEvent.pointerUp(view, { ...end, pointerId: 1, button: 0, buttons: 0 });
  await flush();
}

/** 底图在某个**文档坐标**上的原样(底图与文档同尺寸,所以不用换算)。 */
function original(harness: PixelHarness, x: number, y: number): number[] {
  const data = harness.underlay.data;
  const at = (y * harness.underlay.width + x) * 4;
  return [...data.slice(at, at + 4)];
}

/** 蒙版里第一个"要改"(白)的像素的文档坐标。 */
function firstPainted(harness: PixelHarness): [number, number] {
  const pixels = harness.maskPixels();
  const data = pixels.pixels.data;
  for (let at = 0; at < data.length; at += 4) {
    if (data[at] !== 0) {
      const index = at >> 2;
      return [index % pixels.width, Math.floor(index / pixels.width)];
    }
  }
  throw new Error("蒙版里一个白像素都没有 —— 这一笔没画上去");
}

/** 蒙版里"要改"(白)那些像素的包围盒;一个都没有时给 null。 */
function paintedBounds(harness: PixelHarness): { left: number; top: number; right: number; bottom: number } | null {
  const pixels = harness.maskPixels();
  const data = pixels.pixels.data;
  let left = Infinity;
  let top = Infinity;
  let right = -1;
  let bottom = -1;
  for (let at = 0; at < data.length; at += 4) {
    if (data[at] === 0) continue;
    const index = at >> 2;
    const x = index % pixels.width;
    const y = Math.floor(index / pixels.width);
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x);
    bottom = Math.max(bottom, y);
  }
  return right < 0 ? null : { left, top, right, bottom };
}

/**
 * 一个**离所有笔迹都够远**的文档坐标 —— "没画过的地方逐字节等于原图"要在这里断言。
 *
 * 手写坐标会被笔刷的半径打中(笔刷是一串半径 24 的圆点,不是一条细线 —— 实测:从 (20,20) 画到
 * (40,40),笔迹包围盒是 (6,16)–(73,83),`(5,5)` 正好在里头)。
 */
function untouched(harness: PixelHarness): [number, number] {
  const bounds = paintedBounds(harness);
  if (!bounds) return [0, 0];
  if (bounds.left > 0) return [0, Math.min(W - 1, bounds.bottom + 8)];
  if (bounds.top > 0) return [Math.min(W - 1, bounds.right + 8), 0];
  if (bounds.right < W - 1) return [W - 1, 0];
  return [0, H - 1];
}

/** 蒙版里 alpha ≠ 255 的像素个数 —— 契约那一条的判据。 */
function transparentInMask(harness: PixelHarness): number {
  const data = harness.maskPixels().pixels.data;
  let count = 0;
  for (let at = 3; at < data.length; at += 4) if (data[at] !== 255) count += 1;
  return count;
}

/**
 * 蒙版里**"要改"的像素个数**(白 = 要改)。
 *
 * 可见画布上"被改动过的像素个数"**必须正好等于它**:合成是逐像素的(压暗 + 着色只作用在
 * 蒙版为白的地方),所以这两个数一处对不上就说明有地方在整张改写底图。用实测值而不是手算的
 * 几何面积 —— 笔刷的圆点半径 24,手算迟早算错(第一版就是这么红的)。
 */
function paintedInMask(harness: PixelHarness): number {
  const data = harness.maskPixels().pixels.data;
  let count = 0;
  for (let at = 0; at < data.length; at += 4) if (data[at] !== 0) count += 1;
  return count;
}

/** 可见画布整张 vs 原图:不一样的像素个数(逐 RGB 比)。 */
function viewDelta(harness: PixelHarness): number {
  const view = harness.viewPixels().pixels.data;
  const reference = harness.underlay.data;
  let different = 0;
  for (let at = 0; at < view.length; at += 4) {
    if (view[at] !== reference[at] || view[at + 1] !== reference[at + 1] || view[at + 2] !== reference[at + 2]) different += 1;
  }
  return different;
}

describe("蒙版编辑只动蒙版:清空 / 撤销 / 橡皮 / 形状(像素级)", () => {
  it("清空:蒙版整张全黑且**完全不透明**,可见画布逐字节等于原图", async () => {
    const harness = await open();
    await pick(harness, "笔刷");
    await hardBrush(harness);
    await drag(harness, [20, 20], [40, 40]);
    await harness.settle();
    //: 先确认画笔真的画上去了(否则"清空之后等于原图"是空转的绿)。
    expect(harness.sample(harness.mask(), 30, 30)).toEqual([255, 255, 255, 255]);
    expect(viewDelta(harness), "画过的地方已经不是原图了").toBe(paintedInMask(harness));
    expect(viewDelta(harness)).toBeGreaterThan(0);

    await press(harness, "清空");
    await harness.settle();

    // ① 蒙版:整张全黑、每个像素 alpha 255(契约:不透明)。
    expect(harness.maskPixels().pixels.data.length).toBe(W * H * 4);
    expect(transparentInMask(harness)).toBe(0);
    for (const [x, y] of [
      [0, 0],
      [30, 30],
      [W - 1, H - 1],
    ]) {
      expect(harness.sample(harness.mask(), x, y), `蒙版 ${x},${y}`).toEqual([0, 0, 0, 255]);
    }
    // ② 可见画布:**逐字节**等于原图(底图还在,而且一点没被动过)。
    expect(viewDelta(harness), "清空之后可见画布必须逐字节等于原图").toBe(0);
    expect(harness.sample(harness.view(), 10, 10)).toEqual(original(harness, 10, 10));
  });

  it("撤销:回到上一步的笔迹,蒙版没有透明像素,可见画布仍是底图 + 笔迹", async () => {
    const harness = await open();
    await pick(harness, "笔刷");
    await hardBrush(harness);
    await drag(harness, [20, 20], [40, 40]);
    await harness.settle();
    const painted = harness.sample(harness.mask(), 30, 30);
    expect(painted).toEqual([255, 255, 255, 255]);

    await press(harness, "清空");
    await press(harness, "撤销");
    await harness.settle();

    // ① 撤销把那一笔还回来了(不是"变成灰白"、也不是停在清空后的黑)。
    const spot = firstPainted(harness);
    expect(harness.sample(harness.mask(), spot[0], spot[1])).toEqual([255, 255, 255, 255]);
    expect(transparentInMask(harness)).toBe(0);
    // ② 可见画布:没画过的地方**逐字节等于原图**,改动过的像素个数 == 蒙版里"要改"的个数。
    expect(viewDelta(harness)).toBe(paintedInMask(harness));
    expect(paintedInMask(harness), "撤销把那一笔还回来了").toBeGreaterThan(0);
    const quiet = untouched(harness);
    expect(harness.sample(harness.view(), quiet[0], quiet[1]), "没画过的地方逐字节等于原图").toEqual(
      original(harness, quiet[0], quiet[1]),
    );
    expect(harness.sample(harness.view(), spot[0], spot[1])).not.toEqual(BLUE);
  });

  it("橡皮 = 写黑 = 这块不改:擦完可见画布**露出原图**,不是黑也不是透明", async () => {
    const harness = await open();
    await pick(harness, "笔刷");
    await hardBrush(harness);
    await drag(harness, [30, 40], [50, 60]);
    await harness.settle();
    //: 找**一个真的被画成白的**点来擦(不手算几何:笔刷是一串半径 24 的圆点)。
    const painted = paintedInMask(harness);
    expect(painted).toBeGreaterThan(0);
    const spot = firstPainted(harness);
    const before = harness.sample(harness.view(), spot[0], spot[1]);
    expect(before, "这一点在屏幕上已经是'要改'的样子").not.toEqual(original(harness, spot[0], spot[1]));

    await pick(harness, "橡皮");
    await drag(harness, spot, spot);
    await harness.settle();

    // ① 蒙版那一点是**不透明的黑**(写黑 = 这块不改)。
    expect(harness.sample(harness.mask(), spot[0], spot[1])).toEqual([0, 0, 0, 255]);
    expect(transparentInMask(harness)).toBe(0);
    // ② 屏幕上那一点**逐字节等于原图** —— "擦完露出底图",不是 [0,0,0]、也不是透明。
    expect(harness.sample(harness.view(), spot[0], spot[1]), "擦完露出的是原图").toEqual(original(harness, spot[0], spot[1]));
    expect(harness.sample(harness.view(), spot[0], spot[1])).not.toEqual(before);
    // ③ 蒙版里"要改"的像素少了一块(橡皮只动它碰过的那一块);可见画布跟着少同样多。
    expect(paintedInMask(harness), "擦掉了一块").toBeLessThan(painted);
    expect(viewDelta(harness)).toBe(paintedInMask(harness));
  });

  it("橡皮擦没画过的地方:蒙版与可见画布逐字节不变(幂等)", async () => {
    const harness = await open();
    const maskBefore = [...harness.maskPixels().pixels.data];
    const viewBefore = [...harness.viewPixels().pixels.data];

    await pick(harness, "橡皮");
    await drag(harness, [70, 90], [70, 90]);
    await harness.settle();

    expect([...harness.maskPixels().pixels.data]).toEqual(maskBefore);
    expect([...harness.viewPixels().pixels.data]).toEqual(viewBefore);
    expect(transparentInMask(harness)).toBe(0);
  });

  it("关掉「显示底图」时橡皮擦过的地方回到黑(那是契约视图,不是底图)", async () => {
    const harness = await open();
    await pick(harness, "笔刷");
    await hardBrush(harness);
    await drag(harness, [30, 40], [50, 60]);
    await harness.settle();
    const spot = firstPainted(harness);
    await pick(harness, "橡皮");
    await drag(harness, spot, spot);
    await harness.settle();
    const kept = firstPainted(harness);

    fireEvent.click(harness.scope().getByRole("switch", { name: "显示底图" }));
    await flush();
    await harness.settle();
    //: 层表只剩蒙版本身 ⇒ 屏幕上就是导出的那张黑白图:擦过的地方是黑、没擦到的是白。
    expect(harness.sample(harness.view(), spot[0], spot[1]).slice(0, 3)).toEqual([0, 0, 0]);
    expect(harness.sample(harness.view(), kept[0], kept[1]).slice(0, 3)).toEqual([255, 255, 255]);
    //: 而且这一趟之后关掉底图也不该把蒙版改坏。
    expect(transparentInMask(harness)).toBe(0);
  });

  it("形状拖动、清空、撤销之后:底图那一层始终在层表里(没画过的地方逐字节等于原图)", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    await drag(harness, [10, 10], [60, 70]);
    await harness.settle();
    expect(harness.sample(harness.view(), 5, 5), "形状之外仍是原图").toEqual(original(harness, 5, 5));
    expect(harness.sample(harness.view(), 30, 40), "形状里是要改的样子").not.toEqual(original(harness, 30, 40));
    const quiet = untouched(harness);

    await press(harness, "清空");
    await press(harness, "撤销");
    await harness.settle();

    //: 这三下(形状 / 清空 / 撤销)正是维护者报的那三族 —— 每一下之后底图都得原样在。
    expect(harness.sample(harness.view(), quiet[0], quiet[1]), "没被形状碰到的地方逐字节等于原图").toEqual(
      original(harness, quiet[0], quiet[1]),
    );
    expect(harness.sample(harness.view(), W - 3, H - 3), "右下角(纯红)也原样").toEqual([255, 0, 0, 255]);
    expect(transparentInMask(harness)).toBe(0);
    //: 合成走的是那三层(底图 source-over → 反相 multiply → 着色 lighter),不是"蒙版整张盖上去"。
    expect(harness.viewCalls()[0]).toBe("clearRect");
    expect(harness.viewCalls()).toContain("drawImage source-over 1");
    expect(harness.viewCalls().filter((call) => call.includes("difference"))).toEqual([]);
  });

  it("按亮度初始化 / 反选 / 羽化之后:蒙版仍全不透明,没画过的地方仍是原图", async () => {
    const harness = await open();
    await press(harness, "按亮度初始化");
    await press(harness, "反选");
    await featherBy(harness, 8);
    await press(harness, "应用到蒙版");
    await harness.settle();

    expect(transparentInMask(harness)).toBe(0);
    //: 羽化半径 8 会把边晕得很开,到这一步蒙版上可能处处非零 —— 所以这里不断言"还有没有 0",
    //: 断言的是**不变量本身**:屏幕上改动过的像素个数 == 蒙版里"要改"的个数(两边逐像素对应),
    //: 而且笔迹确实进去了(否则这条是空转的绿)。
    const marked = paintedInMask(harness);
    expect(marked).toBeGreaterThan(0);
    expect(viewDelta(harness)).toBe(marked);
  });
});

/** 屏幕坐标(相对画布元素左上角,CSS 像素)直接拖一笔 —— 放大 / 平移之后不能再按"文档 = 屏幕"换算。 */
async function dragOnScreen(harness: PixelHarness, from: [number, number], to: [number, number], button = 0) {
  const view = harness.view();
  const rect = view.getBoundingClientRect();
  const point = ([x, y]: [number, number]) => ({ clientX: rect.left + x, clientY: rect.top + y });
  const buttons = button === 1 ? 4 : 1;
  fireEvent.pointerDown(view, { ...point(from), pointerId: 2, button, buttons });
  await flush();
  fireEvent.pointerMove(view, { ...point(to), pointerId: 2, button, buttons });
  await flush();
  fireEvent.pointerUp(view, { ...point(to), pointerId: 2, button, buttons: 0 });
  await flush();
}

/**
 * ## 相机只改"怎么看",笔落在哪由相机反算(ADR 0057 决定 3)
 *
 * 放大 / 平移之后,同一个屏幕点对应的文档点变了:矩形落进蒙版的位置必须正好是 `(屏幕 − 偏移) / 缩放`。
 * 把 `docPoint` 换回"按元素矩形等比换算"(放大之前那一版),这条立刻红 —— 笔会落在没放大时的位置。
 */
describe("放大与平移之后,笔落在指针下面那个文档像素上", () => {
  it("放大一档(以画布中心为锚)、再中键平移:矩形在蒙版里的位置按相机反算", async () => {
    const harness = await open();
    const frame = () => document.querySelector<HTMLElement>("[data-mask-doc-frame]")!;
    //: 盒子 = 文档,适应窗口那一档是恒等映射。
    expect(frame().style.transform).toBe("translate(0px, 0px)");

    await press(harness, "放大");
    //: 以中心 (48, 60) 为锚放大 1.25 倍:偏移 = 中心 − 中心 × 1.25。
    expect(frame().style.transform).toBe("translate(-12px, -15px)");
    expect(frame().style.width).toBe(`${W * 1.25}px`);
    expect(frame().style.height).toBe(`${H * 1.25}px`);
    expect(harness.view().getAttribute("width"), "放大不改位图(只改相机)").toBe(String(W));

    await pick(harness, "矩形");
    await dragOnScreen(harness, [28, 35], [68, 80]);
    await harness.settle();
    //: (28 + 12) / 1.25 = 32,(35 + 15) / 1.25 = 40;(68 + 12) / 1.25 = 64,(80 + 15) / 1.25 = 76。
    expect(paintedBounds(harness)).toEqual({ left: 32, top: 40, right: 63, bottom: 75 });

    await press(harness, "清空");
    await dragOnScreen(harness, [10, 10], [30, 20], 1);
    expect(frame().style.transform, "中键拖动只平移").toBe("translate(8px, -5px)");
    expect(paintedBounds(harness), "平移不画").toBeNull();

    await dragOnScreen(harness, [28, 35], [68, 80]);
    await harness.settle();
    //: (28 − 8) / 1.25 = 16,(35 + 5) / 1.25 = 32;(68 − 8) / 1.25 = 48,(80 + 5) / 1.25 = 68。
    expect(paintedBounds(harness)).toEqual({ left: 16, top: 32, right: 47, bottom: 67 });
    expect(transparentInMask(harness)).toBe(0);
  });
});

/**
 * ## 写入口那道闸(**不挂组件**,直接对着它试)
 *
 * 组件那几条断言的是"行为对";这一条断言的是"**根本没有第二条路**":拿不到原始 ctx,写不满整张就抛,
 * 尺寸不符的快照整张不动。把 `MaskContext` 上那两句去掉,它立刻红 —— 那正是这条用例的因果。
 */
describe("写入口那道闸:组件之外也绕不过去", () => {
  it("部分覆盖的写被拒绝;整张的写与清空照常;尺寸不符的快照整张不动", () => {
    const writer = createMaskWriter();
    const ctx = writer.resize(4, 3);
    expect(ctx.size).toEqual({ width: 4, height: 3 });
    //: 黑底本来就是整张写进去的(而且每个像素不透明)。
    expect(pixelOf(writer.canvas() as HTMLCanvasElement).pixels.data.length).toBe(4 * 3 * 4);

    const raw = pixelOf(writer.canvas() as HTMLCanvasElement).getContext("2d")!;
    const image = raw.createImageData(4, 3);
    for (let at = 0; at < image.data.length; at += 4) image.data.set([255, 255, 255, 255], at);
    ctx.write(image);
    expect([...pixelOf(writer.canvas() as HTMLCanvasElement).pixels.data.slice(0, 4)]).toEqual([255, 255, 255, 255]);

    //: 只覆盖一角 —— 拒绝(没碰到的地方会保持原样,而"原样"凭什么还是不透明?这条闸不猜)。
    const partial = raw.createImageData(2, 2);
    expect(() => ctx.write(partial)).toThrow(/does not cover the whole surface/);
    expect(writer.refused.length).toBeGreaterThan(0);

    //: 尺寸不符的快照:整张不动(true = 写了,false = 拒绝)。
    expect(ctx.restore(new Uint8ClampedArray(4 * 3 - 1))).toBe(false);
    expect(ctx.restore(new Uint8ClampedArray(4 * 3))).toBe(true);

    //: 清空照常(它是不透明那条底线)。
    ctx.clear();
    expect([...pixelOf(writer.canvas() as HTMLCanvasElement).pixels.data.slice(0, 4)]).toEqual([0, 0, 0, 255]);
  });

  /**
   * **上一轮那个形状工具的 bug 就是这一条**:拖到一半底图才读进来,文档从 1024² 换成了源图那个
   * 尺寸(维护者那张 1624×2880)—— 按下时那份快照于是比文档**短**。旧写法照写不误:
   * `createImageData` **零填充**、`writeGrayscale` 只写得下它覆盖得到的那一段 ⇒ 剩下的像素全是
   * `alpha 0` ⇒ 合成那两层遇透明像素保持底色 ⇒ 整块被蒙版色糊住 = "变灰"。
   *
   * 这里把那个时刻单独搭出来:小文档 → 取快照 → 文档长大 → 把旧快照写回去。
   */
  it("文档换尺寸之后,旧尺寸的快照写不进去:蒙版一个透明像素都不会多", () => {
    const writer = createMaskWriter();
    const before = writer.resize(8, 8);
    before.clear();
    const snapshot = before.snapshot();

    const after = writer.resize(96, 120);
    //: 先算"漏了多少"再断言谁是红的:这样去掉闸之后,红的这一条**自己就把数字报出来**
    //: (实测 11456 = 96×120 − 8×8,正好是零填充那一段)。
    const accepted = after.restore(snapshot);
    const data = pixelOf(writer.canvas() as HTMLCanvasElement).pixels.data;
    let notOpaque = 0;
    let firstAt = -1;
    for (let at = 3; at < data.length; at += 4) {
      if (data[at] !== 255) {
        notOpaque += 1;
        if (firstAt < 0) firstAt = at >> 2;
      }
    }
    expect({ accepted, notOpaque, firstAt }, "短了一截的快照必须被拒绝,蒙版不许出现透明像素").toEqual({
      accepted: false,
      notOpaque: 0,
      firstAt: -1,
    });
    //: 新文档整张仍然是黑底(旧快照那 64 个像素没有资格改写它)。
    expect([...data.slice(0, 4)]).toEqual([0, 0, 0, 255]);
    expect(data.length).toBe(96 * 120 * 4);
  });
});

/** 一张画布上"亮"(要改)的那些像素:个数 + 包围盒。预览变了没有,看的就是它们。 */
function brightStats(pixels: PixelCanvas): { count: number; bounds: { left: number; top: number; right: number; bottom: number } | null } {
  const data = pixels.pixels.data;
  let count = 0;
  let left = Infinity;
  let top = Infinity;
  let right = -1;
  let bottom = -1;
  for (let at = 0; at < data.length; at += 4) {
    if (data[at] === 0) continue;
    count += 1;
    const index = at >> 2;
    const x = index % pixels.width;
    const y = Math.floor(index / pixels.width);
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x);
    bottom = Math.max(bottom, y);
  }
  return { count, bounds: right < 0 ? null : { left, top, right, bottom } };
}

function brightBounds(pixels: PixelCanvas): { left: number; top: number; right: number; bottom: number } {
  const { bounds } = brightStats(pixels);
  if (!bounds) throw new Error("这张画布上一个亮的像素都没有 —— 这一笔没画上去?");
  return bounds;
}

/** 某一「行」里最左边那个亮的像素 —— 笔迹是一坨(圆点串),包围盒的左沿未必落在中间那一行。 */
function leftmostInRow(pixels: PixelCanvas, row: number): number {
  for (let x = 0; x < pixels.width; x += 1) if (pixels.pixels.data[(row * pixels.width + x) * 4] !== 0) return x;
  throw new Error(`第 ${row} 行没有亮的像素`);
}

/** 指针那个圈(纯显示、不接指针 —— 只能按 data 属性找它)。 */
function brushRing(): HTMLElement {
  const found = document.querySelector<HTMLElement>("[data-mask-brush-ring]");
  if (!found) throw new Error("没有找到指针那个圈");
  return found;
}

/**
 * 圈上那几个渐变色标的百分比 —— 软边的**形状**就是它:硬核到哪一格、外沿在哪。
 *
 * 去重 + 排序:圈的填充是**深浅两层**同一条曲线(见 brushRingFill),每一层各报一遍那两个色标
 * (0 / 硬核 / 100);断言要的是"硬核到哪一格",不是"写了几层"。
 */
function ringStops(): number[] {
  return [...new Set([...brushRing().style.background.matchAll(/([\d.]+)%/g)].map((one) => Number(one[1])))].sort(
    (left, right) => left - right,
  );
}

/** 指针挪到文档坐标 (x,y)(这一座里盒子 = 文档,所以它同时是屏幕坐标)。 */
function hover(harness: PixelHarness, x: number, y: number) {
  fireEvent.pointerMove(harness.view(), { ...at(harness, x, y), pointerId: 1, buttons: 0 });
}

/**
 * ## 笔刷硬度 → 指针那个圈(维护者:「笔刷硬度…在 UI 上没有体现」)
 *
 * 圈此前是一道写死的 1px 硬白边:硬度拖到 10% 和 100% 看上去一模一样,而画出来的笔迹一个是软边、
 * 一个是硬边。现在它的**填充**就是 `paintLine` 会画出来的那条曲线(内圈硬核到 `radius × hardness`,
 * 外面渐隐到半径)—— 两处共用同一个 `HARD_EDGE` 判据,不会分叉。
 *
 * 这几条只断言**圈的样子**:蒙版的像素一个都不该因此改变。
 */
describe("笔刷硬度 → 指针那个圈", () => {
  it("硬度 = 1:圈是硬边 —— 整块实心,没有渐变", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    expect(brushRing().hidden, "指针在画布上、工具是画笔 ⇒ 圈该在").toBe(false);
    expect(brushRing().style.width, "直径 = 笔刷大小 × 相机缩放(这里都是 1)").toBe("48px");

    await hardBrush(harness);
    expect(brushRing().hidden).toBe(false);
    const fill = brushRing().style.background;
    expect(fill, "硬边的圈必须有填充(空串 = 圈又变回一条什么也说不出的边)").not.toBe("");
    expect(fill, "硬度 1 = 利落硬边:没有软的那一段").not.toContain("radial-gradient");
    expect(ringStops(), "没有渐变就没有百分比色标").toEqual([]);
  });

  it("硬度 < 1:圈带软边 —— 硬核到 hardness 那一档,外圈渐隐(不用等下一次移动)", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    await hardBrush(harness);
    expect(brushRing().style.background).not.toContain("radial-gradient");

    //: 从 100% 往左退 10 档 = 50%。**这中间指针一次都没动** —— 滑块一拖圈就得跟着变。
    const slider = sliderWith(harness, (one) => one.getAttribute("aria-valuemax") === "1", "硬度");
    await stepSlider(slider, "ArrowLeft", 10);
    expect(slider.getAttribute("aria-valuenow")).toBe("0.5");

    expect(brushRing().style.background).toContain("radial-gradient");
    expect(ringStops(), "0% → 硬核 50% → 100% 渐隐到边").toEqual([0, 50, 100]);
    //: 圈的大小和位置没被这一下动过(改的只是软硬)。
    expect(brushRing().style.width).toBe("48px");
  });

  it("笔刷大小与指针位置:圈立刻跟着变", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    expect(brushRing().style.transform).toBe("translate(6px, 16px)");

    hover(harness, 50, 60);
    expect(brushRing().style.transform, "圈跟着指针走").toBe("translate(26px, 36px)");

    //: 48 → 49(一档),**中间没有移动指针**:拖大小滑块也得当场反映。
    await stepSlider(sliderWith(harness, (one) => one.getAttribute("aria-valuemax") === "400", "笔刷大小"), "ArrowRight", 1);
    expect(brushRing().style.width).toBe("49px");
    expect(brushRing().style.transform, "变大是往外长,圆心还在指针那一点").toBe("translate(25.5px, 35.5px)");
  });

  it("形状工具与平移:圈收起来(它不是形状的预览)", async () => {
    const harness = await open();
    await pick(harness, "矩形");
    hover(harness, 30, 40);
    expect(brushRing().hidden).toBe(true);

    await pick(harness, "橡皮");
    hover(harness, 30, 40);
    expect(brushRing().hidden, "橡皮也有大小,圈该回来").toBe(false);
  });
});

/**
 * ## 扩张 / 羽化 → 画布上的预览副本(维护者:「边缘的扩张和羽化在 UI 上没有体现」)
 *
 * 这两根滑块此前只在点「应用到蒙版」那一刻才作用到蒙版:拖动时屏幕上**什么都没有**,用户是"点下去
 * 才知道这一步长什么样"。现在待应用时显示层用一份**预览副本**(对当前蒙版算 `growMask` + `featherMask`),
 * 真蒙版一个字节都不动 —— 所以下面每一条都同时钉两件事:可见画布上那个变化**在**,
 * 而 `maskPixels()` 逐字节**没变**。
 *
 * 「显示底图」关掉之后可见画布上就只剩蒙版那一张(层表只剩 `mask`),断言的字节 = 屏幕上看到的那份。
 */
describe("扩张 / 羽化 → 画布上的预览副本(真蒙版不动)", () => {
  /** 关掉「显示底图」:可见画布上只剩蒙版自己 —— 屏幕上是什么就是那一份的字节。 */
  async function maskOnly(harness: PixelHarness) {
    fireEvent.click(harness.scope().getByRole("switch", { name: "显示底图" }));
    await flush();
    await harness.settle();
  }

  /** 画一团白的(硬度 100%:笔迹只有 0 和 255,断言不用挑值)。 */
  async function blob(harness: PixelHarness) {
    await pick(harness, "笔刷");
    await hardBrush(harness);
    await drag(harness, [30, 40], [50, 60]);
    await harness.settle();
  }

  /** 预览是 debounce 过的(拖完约 120ms 才算那一张):等它上屏,而不是"等 0 毫秒"。 */
  async function previewShows(harness: PixelHarness, spot: [number, number]) {
    await waitFor(() => expect(harness.sample(harness.view(), ...spot)[0], "预览没上屏").toBeGreaterThan(0));
  }

  it("扩张 +4:可见画布上那一圈长出来了,真蒙版逐字节没变;滑块归零就回到真蒙版", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);

    const blobBounds = brightBounds(harness.viewPixels());
    const middle = Math.round((blobBounds.top + blobBounds.bottom) / 2);
    const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];
    const before = brightStats(harness.viewPixels()).count;
    expect(harness.sample(harness.view(), ...outside), "扩张之前:这一点在笔迹外").toEqual([0, 0, 0, 255]);
    const maskBefore = [...harness.maskPixels().pixels.data];

    await setGrow(harness, 4);
    await previewShows(harness, outside);

    // ① 预览在:屏幕上"要改"的那一块变大了。
    expect(brightStats(harness.viewPixels()).count, "可见画布上的笔迹长出来了(预览)").toBeGreaterThan(before);
    // ② 真蒙版一个字节都没动(预览只是一份喂给显示层的副本)。
    expect([...harness.maskPixels().pixels.data], "预览不许碰真蒙版").toEqual(maskBefore);
    expect(harness.sample(harness.mask(), ...outside)).toEqual([0, 0, 0, 255]);
    expect(transparentInMask(harness)).toBe(0);

    // ③ 滑块归零 ⇒ 屏幕上回到真蒙版(预览不是"留在那里"的一层)。
    await setGrow(harness, 0);
    await waitFor(() => expect(harness.sample(harness.view(), ...outside)).toEqual([0, 0, 0, 255]));
    expect([...harness.maskPixels().pixels.data]).toEqual(maskBefore);
  });

  it("羽化 8:边两侧晕成灰的,真蒙版还是原来那条硬边、逐字节没变", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);

    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    const edge: [number, number] = [leftmostInRow(harness.viewPixels(), middle), middle];
    const outside: [number, number] = [edge[0] - 2, middle];
    expect(harness.sample(harness.mask(), ...edge), "这一笔的边缘是硬边").toEqual([255, 255, 255, 255]);
    expect(harness.sample(harness.mask(), ...outside)).toEqual([0, 0, 0, 255]);
    const maskBefore = [...harness.maskPixels().pixels.data];

    await featherBy(harness, 8);
    await previewShows(harness, outside);

    // ① 晕开的是**灰的**:边上不再是纯白,外面也不再是纯黑 —— 一眼看得出"这一步是羽化"。
    const softOutside = harness.sample(harness.view(), ...outside)[0];
    expect(softOutside).toBeLessThan(255);
    const softEdge = harness.sample(harness.view(), ...edge)[0];
    expect(softEdge).toBeGreaterThan(0);
    expect(softEdge).toBeLessThan(255);
    // ② 真蒙版:还是原来那条硬边,逐字节没变。
    expect([...harness.maskPixels().pixels.data]).toEqual(maskBefore);
    expect(harness.sample(harness.mask(), ...edge)).toEqual([255, 255, 255, 255]);
    expect(harness.sample(harness.mask(), ...outside)).toEqual([0, 0, 0, 255]);
    expect(transparentInMask(harness)).toBe(0);
  });

  it("待应用时又画了一笔:屏幕上不会停在一份旧副本上(副本按蒙版的版本过期)", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);
    await setGrow(harness, 4);
    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    await previewShows(harness, [leftmostInRow(harness.viewPixels(), middle) - 3, middle]);

    //: 离那一坨远远地再来一笔 —— 刚上屏的那份副本里**没有它**(副本是按上一版蒙版算的)。
    const spot: [number, number] = [10, 100];
    expect(harness.sample(harness.view(), ...spot)).toEqual([0, 0, 0, 255]);
    await drag(harness, spot, spot);
    await waitFor(() =>
      expect(harness.sample(harness.view(), ...spot)[0], "新的一笔没上屏 —— 屏幕停在一份旧副本上了").toBeGreaterThan(0),
    );
    expect(harness.sample(harness.mask(), ...spot)[0], "这一笔真的落在真蒙版上").toBeGreaterThan(0);
  });

  it("点「应用到蒙版」才写进真蒙版:写进去的正是刚才预览的那一份,而且一步撤销", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);
    const maskBefore = [...harness.maskPixels().pixels.data];
    const paintedBefore = paintedInMask(harness);

    await setGrow(harness, 4);
    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];
    await previewShows(harness, outside);
    const preview = [...harness.viewPixels().pixels.data];
    expect([...harness.maskPixels().pixels.data], "还没点应用:真蒙版没动").toEqual(maskBefore);

    await press(harness, "应用到蒙版");
    await harness.settle();

    // ① 真蒙版变了,而且写进去的正是预览里那一点。
    expect(paintedInMask(harness), "真蒙版长出来了").toBeGreaterThan(paintedBefore);
    expect(harness.sample(harness.mask(), ...outside)[0]).toBeGreaterThan(0);
    expect(transparentInMask(harness)).toBe(0);
    // ② 屏幕上正是刚才预览的那一份:应用之后**不会再预览一遍**(那会再多 4 个像素,一眼看得出)。
    expect([...harness.viewPixels().pixels.data], "应用的结果 == 刚才的预览,没有二次扩张").toEqual(preview);

    // ③ 一步撤销回到应用之前(那一步是「应用边缘」自己那一步,不是两笔)。
    await press(harness, "撤销");
    await harness.settle();
    expect([...harness.maskPixels().pixels.data], "一步撤销回到应用之前").toEqual(maskBefore);
    //: 撤销之后滑块还是 4,而这一版蒙版又没被写过 ⇒ 回到"待应用":屏幕上重新是同一份预览。
    await waitFor(() => expect([...harness.viewPixels().pixels.data]).toEqual(preview));
  });
});
