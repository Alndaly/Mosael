/** @vitest-environment jsdom */
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetCanvases, installPixelCanvas, pixelOf } from "@/test/pixelCanvasSetup";
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

async function pick(harness: PixelHarness, name: string) {
  fireEvent.click(harness.scope().getByRole("radio", { name }));
  await flush();
}

async function press(harness: PixelHarness, name: string) {
  fireEvent.click(harness.scope().getByRole("button", { name }));
  await flush();
}

/**
 * 把「笔刷硬度」推到 100%。
 *
 * 默认 90% 的笔刷是**一串径向渐变** —— 笔迹边缘是中间灰(实测 30 / 89 / 145 这些值),
 * 于是"蒙版那点是 255"这种断言会随机红。推到 100% 走的是实心那一条(`hardness >= 0.99`),
 * 笔迹就只有 0 和 255。
 */
async function hardBrush(harness: PixelHarness) {
  //: radix 的滑块没有 `aria-label`,名字来自外面那个 `<label>` —— 按 `role="slider"` 的名字查不到,
  //: 只能按那口 `aria-valuemax` 认(硬度是 0..1 的那一根)。
  const slider = harness
    .scope()
    .getAllByRole("slider")
    .find((one: HTMLElement) => one.getAttribute("aria-valuemax") === "1") as HTMLElement | undefined;
  if (!slider) throw new Error("没有找到硬度滑块");
  slider.focus();
  for (let i = 0; i < 20; i += 1) {
    fireEvent.keyDown(slider, { key: "ArrowRight", bubbles: true, cancelable: true });
  }
  await flush();
  expect(slider.getAttribute("aria-valuenow")).toBe("1");
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
    await press(harness, "羽化");
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
