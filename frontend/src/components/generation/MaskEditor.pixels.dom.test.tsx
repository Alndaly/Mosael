/** @vitest-environment jsdom */
import { act, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { EDGE_PREVIEW_TRAILING_MS, isEdgePreviewCanvas, previewScale } from "@/components/generation/MaskEditor";
import { createMaskWriter } from "@/lib/maskPixels";
import { loadUnderlay, pixelHarness, type PixelHarness } from "@/test/maskEditorPixels";
import { canvasesOfSize, forgetCanvases, installPixelCanvas, pixelOf, type PixelCanvas } from "@/test/pixelCanvasSetup";

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

/**
 * 和 `open()` 一样,但画布**盒子只有文档的一半**(比例一致)。
 *
 * 可见那张位图 = 盒子 ⇒ 文档在屏幕上只有 48×60 个像素,而文档自己是 96×120 —— 「预览副本按显示
 * 分辨率算」那一条要的就是这个差。
 */
async function openHalfSize(): Promise<PixelHarness> {
  const harness = pixelHarness({ width: W, height: H, box: { width: W / 2, height: H / 2 } });
  harness.mount();
  await waitFor(() => expect(harness.view()).toBeTruthy());
  await loadUnderlay(harness);
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
 * 默认 90% 的笔刷边上有一条 `半径 × (1 − 0.9)` 宽的过渡带 —— 边缘那几格是中间灰,
 * 于是"蒙版那点是 255 / 那一行只有 0 和 255"这类断言会红。推到 100% 走的是实心那一条
 * (`HARD_EDGE`),笔迹就只有 0 和 255(同一个判据也是那个圈变硬的判据、形状只填一次的判据)。
 */
async function hardBrush(harness: PixelHarness) {
  const slider = fieldSlider(harness, "笔刷硬度");
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
 * 只能按这两口数字认:羽化 0..64、扩张 −64..64、笔刷大小 2..400。
 *
 * **0..1 那三根(硬度 / 不透明度 / 阈值)不要用它**:范围一样,找到的只是 DOM 里第一个 ——
 * 用 `fieldSlider` 按那一行的名字认。
 */
function sliderWith(harness: PixelHarness, match: (one: HTMLElement) => boolean, what: string): HTMLElement {
  const found = harness.scope().getAllByRole("slider").find((one: HTMLElement) => match(one)) as HTMLElement | undefined;
  if (!found) throw new Error(`没有找到${what}滑块`);
  return found;
}

/**
 * 按**那一行的名字**认一根滑块(`SliderField` 渲染成 `<label><span>名字</span><Slider/>…</label>`)。
 *
 * 比 `sliderWith` 按范围认更稳:范围是会撞的 —— 硬度 / **不透明度** / 阈值三根都是 0..1,
 * 按 `aria-valuemax === "1"` 找到的是**第一个**(= 硬度,靠 DOM 顺序才没出错)。
 */
function fieldSlider(harness: PixelHarness, label: string): HTMLElement {
  const row = harness.scope().getByText(label, { selector: "span" }).closest("label");
  if (!row) throw new Error(`「${label}」那一行不是一个 <label>`);
  return within(row).getByRole("slider");
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

/**
 * 圈里那两层墨的不透明度(取最浓的那一层)—— 「硬度越低越透明」看的数。
 *
 * 那一串里有四个带 alpha 的颜色:两层墨(0.35 / 0.45 那一对)和两个透明的渐隐端(alpha 0)。
 * 取最大 = 圈上最浓的那一点有多浓。
 */
function ringAlpha(): number {
  const alphas = [...brushRing().style.background.matchAll(/rgba\([^)]*?,\s*([\d.]+)\)/g)].map((one) => Number(one[1]));
  if (!alphas.length) throw new Error("圈上没有半透明的墨 —— 填充又变回一条什么也说不出的边了?");
  return Math.max(...alphas);
}

/** 指针挪到文档坐标 (x,y)(这一座里盒子 = 文档,所以它同时是屏幕坐标)。 */
function hover(harness: PixelHarness, x: number, y: number) {
  fireEvent.pointerMove(harness.view(), { ...at(harness, x, y), pointerId: 1, buttons: 0 });
}

/**
 * ## 笔刷硬度 → 指针那个圈(维护者:「笔刷硬度…在 UI 上没有体现」)
 *
 * 上一版把曲线写进了圈的 `style.background`,可那个 div 的 className 里还留着一道**写死的**
 * `border border-white` + 一圈 `shadow`:那道硬白圈盖在渐变上面,于是拖硬度屏幕上一动不动
 * —— 维护者第二次报的「还是没体现」就是它。现在圈上只有 `brushRingFill` 这一样东西决定观感
 * (没有常量边框):它的**填充**就是 `paintLine` 会画出来的那条曲线(内圈硬核到 `radius × hardness`,
 * 外面渐隐到半径),而且那两层墨的浓度也随硬度走(维护者:「应该和透明度有关系」)——
 * 两处共用同一个 `HARD_EDGE` 判据,不会分叉。
 *
 * 这几条只断言**圈的样子**:蒙版的像素一个都不该因此改变。
 */
describe("笔刷硬度 → 指针那个圈", () => {
  it("圈上不再有那道恒定的硬边(border / shadow)—— 观感只由填充给", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    const classes = brushRing().className;
    expect(classes, "圈上还挂着 Tailwind 的 border 工具类 —— 那就是盖住渐变的硬白圈").not.toMatch(/(^|\s)border(-\S+)?(\s|$)/);
    expect(classes, "圈上还挂着 shadow 工具类 —— 那是硬圈的另外半道").not.toMatch(/(^|\s)shadow(-\S+)?(\s|$)/);
    expect(brushRing().style.background, "没有边框之后,圈的样子全在填充里").not.toBe("");
  });

  it("硬度越低,圈越透明、边越散(维护者:「应该和透明度有关系」)", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    await hardBrush(harness);
    const hard = { alpha: ringAlpha(), stops: ringStops() };
    expect(hard.stops, "硬边 = 没有渐隐的那一段").toEqual([]);

    //: 100% → 10%(退 18 档,每档 5%)。指针一次都没动。
    const slider = fieldSlider(harness, "笔刷硬度");
    await stepSlider(slider, "ArrowLeft", 18);
    expect(slider.getAttribute("aria-valuenow")).toBe("0.1");
    const soft = { alpha: ringAlpha(), stops: ringStops() };

    expect(soft.alpha, "软圈的墨该比硬圈淡(硬度 = 透明度那条关系)").toBeLessThan(hard.alpha);
    expect(soft.stops, "软圈:硬核缩到 10%,外面九成半径都在渐隐").toEqual([0, 10, 100]);
    //: 圈的大小没被这一下动过(改的只是软硬)。
    expect(brushRing().style.width).toBe("48px");
  });

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
    const slider = fieldSlider(harness, "笔刷硬度");
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

  /**
   * 圈说的是**硬度**(边缘过渡),不是**不透明度**(画进蒙版的浓度)——
   * 两根滑块都动了之后,圈只该跟着硬度变。
   */
  it("不透明度不碰那个圈:改浓度,圈的填充一个字节都不变", async () => {
    const harness = await open();
    hover(harness, 30, 40);
    await stepSlider(fieldSlider(harness, "笔刷硬度"), "ArrowLeft", 8); //: 90% → 50%
    const soft = brushRing().style.background;
    expect(ringStops(), "圈上那条曲线是硬度给的").toEqual([0, 50, 100]);

    await stepSlider(fieldSlider(harness, "不透明度"), "ArrowLeft", 18); //: 100% → 10%
    expect(fieldSlider(harness, "不透明度").getAttribute("aria-valuenow")).toBe("0.1");
    expect(brushRing().style.background, "圈跟着不透明度走了 —— 它只该反映硬度").toBe(soft);
    expect(ringStops(), "不透明度动过之后,圈上那条曲线还是硬度给的").toEqual([0, 50, 100]);
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
 * 上一版那份副本是**尾随 debounce**(120ms)算的,而且在**文档全分辨率**上跑:维护者那张
 * 4432×1904 一次几百毫秒,拖滑块时屏幕一动不动、松手才猛地换一帧(第二次报的「不实时、卡顿」)。
 * 现在副本按**显示分辨率**算(长边封在 `MAX_VIEW_EDGE`,见 `previewScale`),而且**两条触发分开**
 * (维护者第三次报的「设置扩张以后 绘制、画笔过程都会非常卡顿」):
 *
 * - **参数变**(grow / feather 滑块)→ 那一次 `paint()` 里当场算,一个计时器都不等
 *   (所以下面 `previewShows` 是"当场断言");
 * - **内容变**(正在画)→ **不每帧算**:落笔期间显示层直接用真蒙版(当帧可见、不卡),
 *   `EDGE_PREVIEW_TRAILING_MS` 之后才把预览追上去(见这个 describe 最后那一条)。
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

  /**
   * 预览**当场**就在屏幕上:参数一变,下一次 `paint()` 画上去的就是新副本。
   *
   * 此前这里要 `waitFor` 一圈(尾随 debounce:松手 120ms 之后才算那一张)—— 断言"不用等"就得
   * 把**等待**去掉,否则 debounce 回来了它照样绿。
   */
  function previewShows(harness: PixelHarness, spot: [number, number]) {
    expect(harness.sample(harness.view(), ...spot)[0], "预览没在同一帧上屏 —— 还在 debounce?").toBeGreaterThan(0);
  }

  it("拖扩张滑块:同一次 paint 就换预览,不等任何计时器(旧的 120ms debounce 没了)", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);

    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];
    expect(harness.sample(harness.view(), ...outside), "扩张之前:这一点在笔迹外").toEqual([0, 0, 0, 255]);

    //: 假计时器,而且**一个都不推**:预览必须已经上屏。真排了 debounce 的话这里永远是黑的。
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      await setGrow(harness, 4);
      expect(harness.sample(harness.view(), ...outside)[0], "等计时器才换预览 —— 那就是那个 debounce").toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

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
    previewShows(harness, outside);

    // ① 预览在:屏幕上"要改"的那一块变大了。
    expect(brightStats(harness.viewPixels()).count, "可见画布上的笔迹长出来了(预览)").toBeGreaterThan(before);
    // ② 真蒙版一个字节都没动(预览只是一份喂给显示层的副本)。
    expect([...harness.maskPixels().pixels.data], "预览不许碰真蒙版").toEqual(maskBefore);
    expect(harness.sample(harness.mask(), ...outside)).toEqual([0, 0, 0, 255]);
    expect(transparentInMask(harness)).toBe(0);

    // ③ 滑块归零 ⇒ 屏幕上回到真蒙版(预览不是"留在那里"的一层)。
    await setGrow(harness, 0);
    expect(harness.sample(harness.view(), ...outside)).toEqual([0, 0, 0, 255]);
    expect([...harness.maskPixels().pixels.data]).toEqual(maskBefore);
  });

  it("副本按**显示分辨率**算(盒子是文档的一半 ⇒ 48×60),幅度和真蒙版那一下同一档", async () => {
    const harness = await openHalfSize();
    await blob(harness);
    await maskOnly(harness);
    expect([harness.view().width, harness.view().height], "可见那张位图 = 盒子").toEqual([W / 2, H / 2]);
    const docBoundsBefore = paintedBounds(harness);
    if (!docBoundsBefore) throw new Error("蒙版里一个白像素都没有 —— 这一笔没画上去");
    const maskBefore = [...harness.maskPixels().pixels.data];
    const viewLeftBefore = brightBounds(harness.viewPixels()).left;
    const canvasesBefore = canvasesOfSize(W, H).length;

    await setGrow(harness, 4);
    //: 等的是"预览有没有上屏"这个条件,不是时间(两种分辨率下它都会上屏)。
    await waitFor(() => expect(brightBounds(harness.viewPixels()).left, "预览没上屏").toBeLessThan(viewLeftBefore));

    // ① 副本是在**显示分辨率**上算的:文档全分辨率上没有因此多出第二张画布(旧版正是在 96×120 上跑),
    //:   而副本自己那张正好是显示层那个尺寸(48×60 —— 长边封在 MAX_VIEW_EDGE 里、也不超过可见位图)。
    expect(canvasesOfSize(W, H).length, "预览又在文档全分辨率上另开了一张画布").toBe(canvasesBefore);
    const previews = canvasesOfSize(W / 2, H / 2).filter((one) => isEdgePreviewCanvas(one));
    expect(previews.length, "没有那张按显示分辨率算的预览副本").toBe(1);
    expect([previews[0].width, previews[0].height]).toEqual([W / 2, H / 2]);
    // ② 屏幕上长出来的幅度和「应用到蒙版」那一下同一档:4 个文档像素 = 这里 2 个(实测就是 2;
    //:   留一格余地是因为降采样取最近邻,边缘落在哪半格跟着笔迹的奇偶走)。
    const grewInView = viewLeftBefore - brightBounds(harness.viewPixels()).left;
    expect(grewInView, "预览长出来的幅度和真蒙版那一下对不上").toBeGreaterThanOrEqual(1);
    expect(grewInView).toBeLessThanOrEqual(3);
    // ③ 真蒙版一个字节都没动(预览始终只是一份喂给显示层的副本)。
    expect([...harness.maskPixels().pixels.data]).toEqual(maskBefore);

    await press(harness, "应用到蒙版");
    await harness.settle();
    const applied = paintedBounds(harness);
    if (!applied) throw new Error("应用之后蒙版里一个白像素都没有");
    expect(applied.left, "真蒙版这一步正是扩张 4 个文档像素").toBe(docBoundsBefore.left - 4);
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
    //: 参照取**扩张之前**那一坨(现在参数一变预览就在同一帧上屏,晚了就量到已经长出来的那一份)。
    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    //: 「笔迹外 3 个像素」按**这一行**的左沿算,不拿全图包围盒的左沿:扩张的结构元是**圆盘**
    //: (见 `lib/maskPixels` 的 `growMask`),全图左沿常常落在**别的行**上(实测全图左沿在 y≈44、
    //: 这一行的左沿在 x=8),拿它退 3 格会落到圆盘够不到的地方。同一行退 3 格则方圆两种结构元
    //: 都够得到 —— 而"预览当帧就在"这条断言的分量一点没减。
    const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];
    await setGrow(harness, 4);
    previewShows(harness, outside);

    //: 离那一坨远远地再来一笔 —— 刚上屏的那份副本里**没有它**(副本是按上一版蒙版算的)。
    const spot: [number, number] = [10, 100];
    expect(harness.sample(harness.view(), ...spot)).toEqual([0, 0, 0, 255]);
    await drag(harness, spot, spot);
    //: 这一笔的 paint 里副本就按**新版蒙版**重算了(版本号变了),所以新笔画当场在屏幕上。
    expect(harness.sample(harness.view(), ...spot)[0], "新的一笔没上屏 —— 屏幕停在一份旧副本上了").toBeGreaterThan(0);
    expect(harness.sample(harness.mask(), ...spot)[0], "这一笔真的落在真蒙版上").toBeGreaterThan(0);
  });

  it("点「应用到蒙版」才写进真蒙版:写进去的正是刚才预览的那一份,而且一步撤销", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);
    const maskBefore = [...harness.maskPixels().pixels.data];
    const paintedBefore = paintedInMask(harness);
    //: 参照取**扩张之前**那一坨(预览现在同一帧就上屏,晚一点量到的已经是长出来的那一份了)。
    const bounds = brightBounds(harness.viewPixels());
    const middle = Math.round((bounds.top + bounds.bottom) / 2);
    //: 同上:按**这一行**的左沿退 3 格(圆盘结构元在全图左沿那一行之外够不到)。
    const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];

    await setGrow(harness, 4);
    previewShows(harness, outside);
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
    //: 撤销之后滑块还是 4,而这一版蒙版又没被写过 ⇒ 回到"待应用":屏幕上重新是同一份预览
    //: (每帧当场重算,所以撤销那一下的 paint 里就已经换回来了,不用等)。
    expect([...harness.viewPixels().pixels.data]).toEqual(preview);
  });

  /**
   * 那份预览副本的画布 + 它的像素。
   *
   * 只能按登记表认它(`isEdgePreviewCanvas`):真蒙版、可见那张、派生层那张临时画布**尺寸都一样**
   * (这一座里盒子 = 文档、`previewScale` = 1),按尺寸找会摸错人。
   */
  function previewOf(): { element: HTMLCanvasElement; data: Uint8ClampedArray } {
    const element = canvasesOfSize(W, H).find((one) => isEdgePreviewCanvas(one));
    if (!element) throw new Error("没有那份预览副本 —— 待应用时它该有一张");
    return { element, data: pixelOf(element).pixels.data };
  }

  /**
   * ## 两条触发**分开**(维护者:「设置扩张以后 绘制、画笔过程都会非常卡顿」)
   *
   * 病根:重算的 key 里含**内容版本号**(`MaskWriter.revision`),于是**画每一笔 revision 都 +1
   * → 预览每一帧都重算**(显示分辨率下约 90ms)→ 画笔卡成幻灯片。两条触发现在分开:
   *
   * - **参数变**(grow / feather 滑块)= 当场算,一个计时器都不等(维护者要的实时手感);
   * - **内容变**(正在画)= 不每帧算:落笔期间显示层直接喂**真蒙版**(当帧可见、不卡),
   *   `EDGE_PREVIEW_TRAILING_MS` 之后把预览追上。
   *
   * 过期判据没被改坏:副本的 `key` 里**仍然**有 `revision`,所以内容一变那份旧副本当场作废
   * (`displayedMask` 回到真蒙版)—— 只是**追**得晚一点,不是"旧副本继续冒充"。
   *
   * 假计时器(**一个都不推**)是这条用例的度量:`setGrow` 之后预览必须已经上屏(参数那条不排队),
   * 而落笔之后副本必须**逐字节没变**(内容那条不抢跑),推到 120ms 才换。
   */
  it("参数变当帧就换预览;内容变(正在画)一次都不重算 —— 笔画停下来才追上", async () => {
    const harness = await open();
    await blob(harness);
    await maskOnly(harness);

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      //: 先从**扩张之前**那一份(屏幕上就是真蒙版)量出"笔迹外 3 个像素"那一点:生长 4 个像素之后
      //: 它该变亮。`outside` 必须在 `setGrow` **之前**量 —— 之后量到的是已经长出来的沿,再往左
      //: 3 格就跑到预览之外了(这一条实测踩过)。
      const bounds = brightBounds(harness.viewPixels());
      const middle = Math.round((bounds.top + bounds.bottom) / 2);
      const outside: [number, number] = [leftmostInRow(harness.viewPixels(), middle) - 3, middle];
      expect(harness.sample(harness.view(), ...outside), "扩张之前:这一点在笔迹外").toEqual([0, 0, 0, 255]);

      // ① 参数变:**一个计时器都没推**,预览已经在屏幕上。
      await setGrow(harness, 4);
      expect(harness.sample(harness.view(), ...outside)[0], "参数变还要等计时器 —— 那是上一版的 debounce").toBeGreaterThan(0);
      const preview = previewOf();
      const previewBefore = [...preview.data];

      // ② 内容变:离那一坨远远地画一笔 —— 预览**一次都不该重算**。
      const spot: [number, number] = [12, 100];
      await drag(harness, spot, spot);
      expect([...previewOf().data], "画一笔就把预览重算了 —— 那正是每帧 90ms 的根因").toEqual(previewBefore);
      //: 而真蒙版与屏幕**当帧**更新(落笔期间显示层直接喂真蒙版):
      expect(harness.sample(harness.mask(), ...spot)[0], "这一笔得真的落在真蒙版上").toBeGreaterThan(0);
      expect(harness.sample(harness.view(), ...spot)[0], "落笔期间屏幕停在一份旧副本上").toBeGreaterThan(0);
      //: 同一帧上那份**过期**的扩张预览已经退场(显示层不是"停着旧副本",是真蒙版)。
      expect(harness.sample(harness.view(), ...outside)[0], "落笔期间屏幕上还挂着过期的那份扩张预览").toBe(0);

      // ③ 笔画告一段落(尾随 120ms)→ 预览追上,而且追的是**这一版**蒙版。
      const maskAfterStroke = [...harness.maskPixels().pixels.data];
      await act(async () => {
        vi.advanceTimersByTime(EDGE_PREVIEW_TRAILING_MS);
      });
      expect([...previewOf().data], "停手之后预览没追上").not.toEqual(previewBefore);
      expect(harness.sample(harness.view(), ...outside)[0], "追上之后扩张那一圈该回来").toBeGreaterThan(0);
      //: 追上这一下也只是一份喂给显示层的副本 —— 真蒙版逐字节没动。
      expect([...harness.maskPixels().pixels.data], "预览那次重算碰了真蒙版").toEqual(maskAfterStroke);
    } finally {
      vi.useRealTimers();
    }
  });
});

/**
 * ## 预览副本的分辨率(`previewScale`)
 *
 * 上面那条测的是"屏幕上那份副本确实小了一号";这一条把**规则**本身钉住 —— 长边封在显示层那个
 * `MAX_VIEW_EDGE`(2048,显示层位图的上限)里,也不超过可见那张位图,而小文档原样算(1)。
 */
describe("预览副本的分辨率(previewScale)", () => {
  it("长边封在显示层的 2048 里,也不超过可见那张位图;小文档原样", () => {
    expect(previewScale({ width: 96, height: 120 }, { width: 96, height: 120 }), "文档本来就够小 ⇒ 原样算").toBe(1);
    //: 维护者那张 4432×1904:显示层位图 2048×880 都够用,副本按 2048/4432 ≈ 0.462 缩。
    const big = previewScale({ width: 4432, height: 1904 }, { width: 2048, height: 2048 });
    expect(big).toBeCloseTo(2048 / 4432, 6);
    expect(big * 4432, "长边正好落在显示层上限上").toBeCloseTo(2048, 6);
    //: 画布区小的时候按位图算:盒子只有 600 宽 ⇒ 算 2048 是白算的。
    expect(previewScale({ width: 4432, height: 1904 }, { width: 600, height: 400 })).toBeCloseTo(600 / 4432, 6);
    //: 还没量到位图(jsdom、对话框刚挂上那一帧)时退回"只看长边上限",不是 0(0 会让副本变成 1×1)。
    expect(previewScale({ width: 4432, height: 1904 }, { width: 0, height: 0 })).toBeCloseTo(2048 / 4432, 6);
  });
});

/**
 * ## 五个参数各管一件事:硬度 = **边缘过渡**、不透明度 = **画进蒙版的浓度**
 *
 * 维护者最终定义:
 *
 * | 参数 | 管什么 |
 * | --- | --- |
 * | 大小 | 笔尖直径 |
 * | **硬度** | **每一笔的边缘过渡**(1 = 一刀切,越低越软)。画笔 / 橡皮 / 形状都吃它 |
 * | **不透明度** | **画进蒙版的灰度值** = 蒙版的透明度:`round(不透明度 × 255)` |
 *
 * 两条职责在实现上是**分开的两样东西**:
 *
 * - **浓度靠颜色**:`rgb(v v v)`(`inkColor`),`globalAlpha` 保持 1 ⇒ 同色 dab 重叠是"同一个不透明色
 *   再铺一次",整条笔迹停在 v,**不会叠到 255**;
 * - **软边靠 alpha**:画笔的径向渐变内半径 `半径 × 硬度` → 外半径 `半径`,alpha 从 1 到 0,颜色始终
 *   是那个浓度色;形状按 `半径 × (1 − 硬度)` 往里铺一条分层斜坡(内缩 + 递增 `globalAlpha`,
 *   `SOFT_STEPS` 层)⇒ 内部停在 v、外缘是 `v → 0`。
 *
 * 这里断言的是**蒙版里的灰度**(不是屏幕上那个圈、也不是预览那张副本):契约是逐像素 `r = g = b`,
 * 所以取红通道就是那个灰度。
 */
describe("不透明度 = 浓度 / 硬度 = 边缘过渡(整笔一个灰度)", () => {
  /** 把一根 `0..1`、每档 5% 的滑块推到 `target`。 */
  async function setLevel(slider: HTMLElement, target: number) {
    const from = Number(slider.getAttribute("aria-valuenow"));
    await stepSlider(slider, target >= from ? "ArrowRight" : "ArrowLeft", Math.round(Math.abs(target - from) / 0.05));
    expect(Number(slider.getAttribute("aria-valuenow"))).toBeCloseTo(target, 6);
  }

  /** 把「笔刷硬度」推到 `target`。 */
  const setHardness = (harness: PixelHarness, target: number) => setLevel(fieldSlider(harness, "笔刷硬度"), target);
  /** 把「不透明度」推到 `target`。 */
  const setOpacity = (harness: PixelHarness, target: number) => setLevel(fieldSlider(harness, "不透明度"), target);

  /** 把「笔刷大小」推到 `target`(2..400,每档 1 像素)。 */
  async function setBrush(harness: PixelHarness, target: number) {
    const slider = fieldSlider(harness, "笔刷大小");
    const from = Number(slider.getAttribute("aria-valuenow"));
    await stepSlider(slider, target >= from ? "ArrowRight" : "ArrowLeft", Math.abs(target - from));
    expect(slider.getAttribute("aria-valuenow")).toBe(String(target));
  }

  /** 蒙版上某一点那一格的灰度。 */
  const grayAt = (harness: PixelHarness, x: number, y: number) => harness.sample(harness.mask(), x, y)[0];

  /** 蒙版里最亮的那一格 —— 「重叠的 dab 不叠到 255」看的就是它。 */
  function brightest(harness: PixelHarness): number {
    const data = harness.maskPixels().pixels.data;
    let most = 0;
    for (let at = 0; at < data.length; at += 4) most = Math.max(most, data[at]);
    return most;
  }

  /** 蒙版里某一行的灰度(左右都闭)。 */
  function maskRow(harness: PixelHarness, y: number, left: number, right: number): number[] {
    const pixels = harness.maskPixels();
    const row: number[] = [];
    for (let x = left; x <= right; x += 1) row.push(pixels.pixels.data[(y * pixels.width + x) * 4]);
    return row;
  }

  /** 画一笔(**先把上一笔清掉**,再放硬度 / 不透明度、选工具、拖)。 */
  async function stroke(
    harness: PixelHarness,
    tool: string,
    { hardness = 1, opacity = 1, from, to }: { hardness?: number; opacity?: number; from: [number, number]; to: [number, number] },
  ) {
    await press(harness, "清空");
    await setHardness(harness, hardness);
    await setOpacity(harness, opacity);
    await pick(harness, tool);
    await drag(harness, from, to);
    await harness.settle();
  }

  /** 一根形状工具的框(左沿 20 / 右沿 90,第 55、60 行都离上下沿够远)。 */
  const RECT: { from: [number, number]; to: [number, number] } = { from: [20, 20], to: [90, 110] };

  it("⓪ 面板:「不透明度」紧跟在「笔刷硬度」下面、默认 100%,文案说清它管的是浓度", async () => {
    const harness = await open();

    const rows = [...harness.scope().getAllByRole("slider")];
    const hardness = fieldSlider(harness, "笔刷硬度");
    const opacity = fieldSlider(harness, "不透明度");
    expect(opacity.getAttribute("aria-valuenow"), "不透明度默认 100%").toBe("1");
    expect(rows.indexOf(opacity), "不透明度要**紧跟**在硬度下面(维护者:面板里紧跟硬度)").toBe(rows.indexOf(hardness) + 1);
    //: 文案得让用户明白它管的是"画进蒙版的浓度",不是第三根"硬度"。
    expect(harness.scope().getByText(/画进蒙版的浓度/), "面板上没有一句话说清不透明度是什么").toBeTruthy();
  });

  it("① 不透明度:100% → 255、50% → 128、0% → 0(画笔 / 矩形 / 椭圆共用同一条定义)", async () => {
    const harness = await open();
    const cases: { tool: string; box: { from: [number, number]; to: [number, number] }; at: [number, number] }[] = [
      { tool: "笔刷", box: { from: [20, 20], to: [60, 60] }, at: [40, 40] },
      { tool: "矩形", box: RECT, at: [55, 60] },
      { tool: "椭圆", box: { from: [10, 10], to: [80, 110] }, at: [45, 60] },
    ];

    for (const { tool, box, at } of cases) {
      await stroke(harness, tool, { opacity: 1, ...box });
      expect(grayAt(harness, ...at), `${tool}:100% 是满浓度`).toBe(255);

      await stroke(harness, tool, { opacity: 0.5, ...box });
      expect(grayAt(harness, ...at), `${tool}:50% = round(0.5 × 255) = 128`).toBe(128);

      await stroke(harness, tool, { opacity: 0, ...box });
      expect(brightest(harness), `${tool}:0% 一点都涂不上(写进去的就是 0 = 这块不改)`).toBe(0);
      expect(paintedInMask(harness), `${tool}:0% 时蒙版里没有"要改"的格子`).toBe(0);
    }
  });

  it("② 同一条笔迹来回蹭三趟,最亮仍是 128 —— 颜色承载浓度,不叠到 255", async () => {
    const harness = await open();
    await press(harness, "清空");
    await setHardness(harness, 1);
    await setOpacity(harness, 0.5);
    await pick(harness, "笔刷");
    //: 同一条线来回蹭三趟(每个 dab 之间本来就重叠:间距是半径的 0.4 倍)。
    for (let pass = 0; pass < 3; pass += 1) {
      await drag(harness, [20, 30], [70, 80]);
      await drag(harness, [70, 80], [20, 30]);
    }
    await harness.settle();

    expect(brightest(harness), "重叠的 dab 叠成 255 了 —— 浓度靠颜色扛,不靠饱和").toBe(128);
    for (const [x, y] of [
      [30, 40],
      [45, 55],
      [60, 70],
      [50, 60],
    ] as [number, number][]) {
      expect(grayAt(harness, x, y), `(${x},${y}) 的浓度该和整条笔迹一样(点位均匀)`).toBe(128);
    }
    expect(transparentInMask(harness)).toBe(0);
  });

  it("③ 硬度 0 的矩形边缘是一条单调斜坡;硬度 1 的只有 0 / v 跳变", async () => {
    const harness = await open();

    //: 半径 24(笔刷 48)+ 硬度 0 ⇒ 过渡带 24 个像素:第 55 行横穿左沿(左沿在 x=20)。
    await stroke(harness, "矩形", { hardness: 0, opacity: 1, ...RECT });
    const ramp = maskRow(harness, 55, 15, 95);
    const inward = ramp.slice(0, 35);
    for (let i = 1; i < inward.length; i += 1) {
      expect(inward[i], `从框外往里第 ${i} 格比上一格还暗 —— 边缘不是一条非降的斜坡`).toBeGreaterThanOrEqual(inward[i - 1]);
    }
    const middle = inward.filter((one) => one > 0 && one < 255);
    expect(middle.length, "硬度 0 的边上没有中间灰 —— 那不是软边").toBeGreaterThan(8);
    expect(new Set(middle).size, "中间那几格全是同一个值 —— 那不是斜坡").toBeGreaterThan(8);
    expect(inward[5], "左沿那一格(深度 1 像素)该接近 0,而不是一上来就满浓度").toBeLessThan(40);
    expect(inward[0], "框外仍是黑的").toBe(0);
    expect(inward[inward.length - 1], "过渡带走完就是满浓度").toBe(255);

    //: 同一把笔刷、同一个框,硬度 1:边缘逐格只有 0 / 255 —— 一刀切,没有过渡带。
    await stroke(harness, "矩形", { hardness: 1, opacity: 1, ...RECT });
    const hard = maskRow(harness, 55, 15, 95);
    expect(new Set(hard), "硬度 100% 的边上出现了中间灰 —— 边缘没有一刀切").toEqual(new Set([0, 255]));
    expect(hard.slice(0, 5), "框外是黑的").toEqual([0, 0, 0, 0, 0]);
    expect(hard.slice(5, 75).every((one) => one === 255), "框里一路平到右沿").toBe(true);
  });

  it("④ 过渡带的宽度 = 笔刷半径 × (1 − 硬度):跟着半径和硬度两个轴走", async () => {
    const harness = await open();
    /** 过渡带有几格:第 60 行从框的左沿(第一格非零)数到第一格满浓度为止。 */
    function bandPixels(): number {
      const row = maskRow(harness, 60, 0, W - 1);
      const start = row.findIndex((one) => one !== 0);
      expect(start, "这一行上没有形状 —— 什么都没画上去?").toBeGreaterThanOrEqual(0);
      let at = start;
      while (at < row.length && row[at] !== 255) at += 1;
      expect(at, "这一行上没有满浓度那一格 —— 形状没铺满?").toBeLessThan(row.length);
      return at - start;
    }

    await setBrush(harness, 48); //: 半径 24
    await stroke(harness, "矩形", { hardness: 0, opacity: 1, ...RECT });
    const soft = bandPixels(); //: 24 × (1 − 0) = 24
    await stroke(harness, "矩形", { hardness: 0.5, opacity: 1, ...RECT });
    const halfway = bandPixels(); //: 24 × (1 − 0.5) = 12
    await setBrush(harness, 96); //: 半径翻倍
    await stroke(harness, "矩形", { hardness: 0.5, opacity: 1, ...RECT });
    const doubled = bandPixels(); //: 48 × (1 − 0.5) = 24 —— 和上面那条一样宽

    expect(soft, "半径 24 / 硬度 0 的过渡带该是 24 格(格数按像素取整,留一点余量)").toBeGreaterThanOrEqual(22);
    expect(soft).toBeLessThanOrEqual(25);
    expect(halfway, "硬度 0.5 的过渡带该是它的一半").toBeGreaterThanOrEqual(10);
    expect(halfway).toBeLessThanOrEqual(13);
    expect(Math.abs(doubled - soft), "半径翻倍 × 硬度 0.5 ≠ 半径 24 × 硬度 0 —— 尺度不是同一个乘积").toBeLessThanOrEqual(2);
  });

  it("⑤ 形状仍是一步撤销:半浓度的矩形,按一下撤销就整张回到画之前", async () => {
    const harness = await open();
    const before = [...harness.maskPixels().pixels.data];
    await stroke(harness, "矩形", { hardness: 1, opacity: 0.5, from: [20, 30], to: [70, 80] });
    expect(grayAt(harness, 45, 55), "先确认真的画进去了(否则这条是空转的绿)").toBe(128);

    await press(harness, "撤销");
    await harness.settle();
    expect([...harness.maskPixels().pixels.data], "一步撤销 = 整张回到画之前").toEqual(before);
    expect(transparentInMask(harness)).toBe(0);
  });

  /**
   * 显示层**不需要改**:合成那条路本来就把蒙版的灰度当"多少浓度"用(`maskViewLayers` 的
   * `maskInverse` multiply + `maskTint` lighter,两者都逐像素乘蒙版),所以 128 的那一点在屏幕上
   * 读出来正好落在"没画过"与"满浓度"之间 —— 既不是"有/无",也不是全浓度。
   *
   * 底图左 2/3 是纯蓝、蒙版色 `--destructive` 的红通道 189 ⇒ 没画 0、半浓度 ≈ 95、满浓度 ≈ 189
   * (压暗那一层乘的是 `255 − 蒙版`,着色那一层乘的是蒙版)。
   */
  it("⑥ 屏幕上的合成按灰度出透明度:半浓度那一点比没画过浓、比满浓度淡", async () => {
    const harness = await open();
    await press(harness, "清空");
    await setHardness(harness, 1);
    await pick(harness, "笔刷");

    //: 满浓度一笔(y≈20)与半浓度一笔(y≈100):两条离得开,采样点各取在笔迹正中。
    await setOpacity(harness, 1);
    await drag(harness, [10, 20], [40, 20]);
    await harness.settle();
    await setOpacity(harness, 0.5);
    await drag(harness, [10, 100], [40, 100]);
    await harness.settle();

    const red = (x: number, y: number) => harness.sample(harness.view(), x, y)[0];
    expect(grayAt(harness, 25, 20), "参照:上面那一笔是满浓度").toBe(255);
    expect(grayAt(harness, 25, 100), "参照:下面那一笔是半浓度").toBe(128);
    expect(grayAt(harness, 25, 60), "参照:中间这一点没被碰过").toBe(0);

    const full = red(25, 20);
    const half = red(25, 100);
    const none = red(25, 60);
    expect(half, "半浓度在屏幕上读不出浓度差(被压成有/无了)").toBeGreaterThan(none);
    expect(half, "半浓度那一格比满浓度还浓").toBeLessThan(full);
  });

  /**
   * **橡皮不吃不透明度**:擦除力度保持满强度(写黑 = `0` = 这块不改)。
   *
   * 理由(同一段话也写在 `MaskEditor` 文件头「橡皮不吃不透明度」):
   *
   * 1. 蒙版是**没有 alpha 的灰度图**,"擦掉"在数据上只能是写黑(`0`)。橡皮的落点值只有**一个**
   *    目标,**没有"半浓的黑"可言** —— 而不透明度那条说的是"往蒙版里**加**多浓",橡皮不加东西;
   * 2. 想让擦除吃不透明度的唯一表达是拿 `globalAlpha = 不透明度` 去混(`v ← v × (1 − 不透明度)`),
   *    而 dab 的间距是半径的 0.4 倍 ⇒ 同一个像素会被同一笔打中五到九次:`(1 − 0.5)⁵ ≈ 0.03`。
   *    结果是**笔迹中间照样擦干净、只有边缘留着一点**,连"擦除力度"都算不上(0% 还会变成
   *    "擦不动",比涂不上更难解释);
   * 3. 于是**唯一**那个浓度定义(`inkGray`)橡皮不消费它 —— 这条决定在这里钉住。
   *
   * 橡皮**吃硬度**(那是"每一笔的边缘过渡",是另一件事):dab 中心照旧是纯 `0`,只有边缘淡出去。
   */
  it("⑦ 橡皮不吃不透明度:50% / 0% 的橡皮擦下去仍是纯黑(中心满强度)", async () => {
    const harness = await open();
    const spot: [number, number] = [40, 50];
    /** 画一团满浓度的白,好让橡皮有东西可擦。 */
    async function whiteBlob() {
      await press(harness, "清空");
      await setOpacity(harness, 1);
      await setHardness(harness, 1);
      await pick(harness, "笔刷");
      await drag(harness, [30, 40], [50, 60]);
      await harness.settle();
      expect(harness.sample(harness.mask(), ...spot), "参照:这一点先得是满浓度").toEqual([255, 255, 255, 255]);
    }
    async function eraseAt(opacity: number, hardness: number) {
      await pick(harness, "橡皮");
      await setHardness(harness, hardness);
      await setOpacity(harness, opacity);
      await drag(harness, spot, spot);
      await harness.settle();
    }

    await whiteBlob();
    await eraseAt(0.5, 1);
    expect(harness.sample(harness.mask(), ...spot), "橡皮的力度跟着不透明度走了 —— 擦完该是纯黑").toEqual([0, 0, 0, 255]);

    await whiteBlob();
    await eraseAt(0, 1);
    expect(harness.sample(harness.mask(), ...spot), "不透明度 0 的橡皮也照擦(擦除只有一个目标值)").toEqual([0, 0, 0, 255]);

    await whiteBlob();
    await eraseAt(0.5, 0.5);
    expect(harness.sample(harness.mask(), ...spot), "橡皮吃硬度 —— 但那是软边,dab 中心仍是满强度(纯黑)").toEqual([
      0, 0, 0, 255,
    ]);
    //: 「橡皮 = 写黑」那条不变量没被这条决定带坏:蒙版里不许漏出透明像素。
    expect(transparentInMask(harness)).toBe(0);
  });
});
