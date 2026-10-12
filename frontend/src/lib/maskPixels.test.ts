/**
 * 蒙版的像素运算:反选、阈值(按亮度 / 按 alpha)、羽化、撤销栈那份单通道。
 *
 * 羽化只断言**关系**(中心被压下去、边上没被碰到),不断言具体数值 —— 三遍盒式模糊的系数是一串
 * 可以算准但改一次实现就全废的小数,而这条测试要守的是「边软了、远处没动」。
 */
import { describe, expect, it } from "vitest";

import {
  MASK_TINT_DIM,
  MASK_TINT_TOKEN,
  alphaMask,
  featherMask,
  grayscaleOf,
  invertMask,
  maskViewLayers,
  thresholdMask,
  writeGrayscale,
  type MaskPixels,
} from "@/lib/maskPixels";

/** 一份 w×h 的像素,全部是同一个颜色(默认:不透明白)。 */
function pixels(width: number, height: number, fill: [number, number, number, number] = [255, 255, 255, 255]): MaskPixels {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let at = 0; at < data.length; at += 4) data.set(fill, at);
  return data;
}

/** (x, y) 那一格的灰度(只取红通道 —— 写进去的必然是灰的)。 */
function at(data: MaskPixels, width: number, x: number, y: number): number {
  return data[(y * width + x) * 4];
}

function set(data: MaskPixels, width: number, x: number, y: number, value: number): void {
  data.set([value, value, value, 255], (y * width + x) * 4);
}

describe("反选", () => {
  it("黑变白、白变黑", () => {
    const data = pixels(3, 1);
    set(data, 3, 0, 0, 0);
    set(data, 3, 1, 0, 255);
    set(data, 3, 2, 0, 128);

    invertMask(data);

    expect([0, 1, 2].map((x) => at(data, 3, x, 0))).toEqual([255, 0, 127]);
  });

  it("灰的按 255 减 —— 羽化过的边翻过来还是同样软的一条边", () => {
    const data = pixels(2, 1);
    set(data, 2, 0, 0, 200);
    set(data, 2, 1, 0, 55);

    invertMask(data);

    expect([0, 1].map((x) => at(data, 2, x, 0))).toEqual([55, 200]);
  });

  it("alpha 填满:蒙版没有透明通道那种读法(红通道,见文件头)", () => {
    const data = pixels(1, 1, [10, 10, 10, 0]);
    invertMask(data);
    expect([...data]).toEqual([245, 245, 245, 255]);
  });
});

describe("阈值二值化", () => {
  it("按亮度:亮过阈值变白,其余变黑(结果只有 0 和 255)", () => {
    const data = pixels(3, 1);
    set(data, 3, 0, 0, 200);
    set(data, 3, 1, 0, 60);
    set(data, 3, 2, 0, 128);

    thresholdMask(data, 0.5);

    expect([0, 1, 2].map((x) => at(data, 3, x, 0))).toEqual([255, 0, 255]);
  });

  it("彩色的底图按亮度加权,不按某一个通道", () => {
    // 纯绿(0,255,0)的亮度是 0.587 —— 阈值 0.5 时算亮,阈值 0.6 时算暗;纯蓝(0,0,255)是 0.114,两头都暗。
    const green = pixels(1, 1, [0, 255, 0, 255]);
    thresholdMask(green, 0.5);
    expect(at(green, 1, 0, 0)).toBe(255);

    const dark = pixels(1, 1, [0, 255, 0, 255]);
    thresholdMask(dark, 0.6);
    expect(at(dark, 1, 0, 0)).toBe(0);

    const blue = pixels(1, 1, [0, 0, 255, 255]);
    thresholdMask(blue, 0.5);
    expect(at(blue, 1, 0, 0)).toBe(0);
  });

  it("阈值两头都是合法输入:0 全白,1 只剩纯白", () => {
    const all = pixels(2, 1);
    set(all, 2, 0, 0, 0);
    set(all, 2, 1, 0, 254);
    thresholdMask(all, 0);
    expect([0, 1].map((x) => at(all, 2, x, 0))).toEqual([255, 255]);

    const strict = pixels(2, 1);
    set(strict, 2, 0, 0, 254);
    set(strict, 2, 1, 0, 255);
    thresholdMask(strict, 1);
    expect([0, 1].map((x) => at(strict, 2, x, 0))).toEqual([0, 255]);
  });

  it("按 alpha:不透明的地方变白(抠好的 PNG 走这条)", () => {
    const data = pixels(3, 1);
    set(data, 3, 0, 0, 255); // alpha 也是 255(set 写的是 [v,v,v,255])
    data.set([10, 10, 10, 0], 4);
    data.set([10, 10, 10, 200], 8);

    alphaMask(data, 0.5);

    expect([0, 1, 2].map((x) => at(data, 3, x, 0))).toEqual([255, 0, 255]);
  });
});

describe("羽化", () => {
  //: 33×33、中间一块 17×17 的白(10..26)。半径 2 的最远影响是每轴 6 格(三遍 × 2):块心离边 8 格够远
  //: (该原样),画布边离白块 10 格够远(该是黑的),而白块边缘那一圈正好落在被晕开的范围里。
  const SIZE = 33;
  const FROM = 10;
  const TO = 26;
  const CENTER = 18;
  /** 紧挨着白块外面的那一列。 */
  const OUT = TO + 1;

  function block(): MaskPixels {
    const data = pixels(SIZE, SIZE, [0, 0, 0, 255]);
    for (let y = FROM; y <= TO; y += 1) {
      for (let x = FROM; x <= TO; x += 1) set(data, SIZE, x, y, 255);
    }
    return data;
  }

  it("块心原样、边上晕开、远处一点没动", () => {
    const data = block();
    featherMask(data, SIZE, SIZE, 2);

    expect(at(data, SIZE, CENTER, CENTER), "块心离边够远,羽化不该动它").toBe(255);
    expect(at(data, SIZE, TO, CENTER), "白块自己的边被啃进去一点").toBeLessThan(255);
    const outside = at(data, SIZE, OUT, CENTER);
    expect(outside, "紧挨着白块的外面该染上一点").toBeGreaterThan(0);
    expect(outside).toBeLessThan(255);
    expect(at(data, SIZE, 0, 0), "角上离得远,不该被碰到").toBe(0);
    expect(at(data, SIZE, SIZE - 1, SIZE - 1)).toBe(0);
  });

  it("半径越大,边越软:白块里面被啃得更多、外面晕得更远", () => {
    const small = block();
    const large = block();
    featherMask(small, SIZE, SIZE, 1);
    featherMask(large, SIZE, SIZE, 3);
    expect(at(large, SIZE, TO, CENTER)).toBeLessThan(at(small, SIZE, TO, CENTER));
    //: 离白块 4 格:半径 1 的模糊够不着(还是纯黑),半径 3 的已经晕到了。
    expect(at(small, SIZE, OUT + 3, CENTER)).toBe(0);
    expect(at(large, SIZE, OUT + 3, CENTER)).toBeGreaterThan(0);
  });

  it("alpha 填满 —— 羽化出来的灰边也不是透明的", () => {
    const data = block();
    featherMask(data, SIZE, SIZE, 2);
    for (let index = 3; index < data.length; index += 4) expect(data[index]).toBe(255);
  });

  it("半径不到 1 像素时什么都不做(0.4px 的模糊看不出来,却是几遍全画布扫描)", () => {
    const data = block();
    const before = [...data];
    featherMask(data, SIZE, SIZE, 0.4);
    expect([...data]).toEqual(before);
  });

  it("尺寸对不上时不动它(宁可不变,也不要按错的宽度重排)", () => {
    const data = block();
    const before = [...data];
    featherMask(data, SIZE, SIZE - 1, 2);
    expect([...data]).toEqual(before);
  });
});

describe("撤销栈那份单通道", () => {
  it("取出来是每像素一个字节,写回去还是那张灰度图、alpha 填满", () => {
    const data = pixels(2, 1);
    set(data, 2, 0, 0, 30);
    set(data, 2, 1, 0, 200);
    data.set([30, 30, 30, 0], 0); // 就算原来带透明(不该有),存下来的也只是灰度

    const channel = grayscaleOf(data);
    expect([...channel]).toEqual([30, 200]);

    const restored = pixels(2, 1, [0, 0, 0, 0]);
    writeGrayscale(channel, restored);
    expect([...restored]).toEqual([30, 30, 30, 255, 200, 200, 200, 255]);
  });

  it("写回时长度以短的为准 —— 尺寸换过的那一帧不至于写出边界", () => {
    const restored = pixels(3, 1, [0, 0, 0, 0]);
    writeGrayscale(new Uint8ClampedArray([255]), restored);
    expect([...restored]).toEqual([255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0]);
  });
});

/**
 * 看得见那张画布的层表。这条守的是维护者报的那个 bug:蒙版是不透明的,`source-over` 整张盖上去
 * 就是一块黑板 —— 底图没了、画过和没画过也分不出来(清空 / 反选之后屏幕一个样)。
 *
 * 断言的是**层表本身**(顺序、混合方式、alpha、颜色):画布那头(`drawMaskView`)只照着它画,
 * 真实像素另有 Chromium 里的探针实测。
 *
 * 蒙版色从这一轮起是**调用方给的**(主题色),所以这里的两个常量是「调用方解析出来的那个颜色」——
 * tokens.css 里 `--destructive` 的浅 / 深两个值。
 */
describe("看得见那张画布的层表", () => {
  const LIGHT_TINT = "#bd383e";
  const DARK_TINT = "#f28d96";
  const shown = (tint = LIGHT_TINT) => maskViewLayers({ hasUnderlay: true, showUnderlay: true, tint });

  it("底图在最下面,蒙版的两层叠在它上面 —— 顺序反了就是那个 bug", () => {
    const plan = shown();
    expect(plan.map((layer) => layer.of)).toEqual(["underlay", "maskInverse", "maskTint"]);
    expect(plan[0]).toEqual({ of: "underlay", op: "source-over", alpha: 1 });
  });

  it("有底图时**没有**哪一层是蒙版整张盖上去:它不透明,盖上去就把底图抹了", () => {
    //: 这一条是那个 bug 的形状:`{ of: "mask", op: "source-over", alpha: 1 }` 画在底图之上。
    expect(shown().filter((layer) => layer.of === "mask")).toEqual([]);
    expect(shown().map((layer) => layer.op)).toEqual(["source-over", "multiply", "lighter"]);
  });

  it("压暗那一层不是全黑,着色那一层不是空转:两笔都得在 0..1 之间真的发生", () => {
    //: 只压暗 = 底图本来就黑的地方看不出来;只着色 = 底图本来就白的地方看不出来 —— 所以是两层。
    expect(shown()[1].alpha).toBe(MASK_TINT_DIM);
    expect(shown()[2].alpha).toBe(1);
    expect(MASK_TINT_DIM).toBeGreaterThan(0);
    expect(MASK_TINT_DIM).toBeLessThan(1);
    //: 蒙版色是**一个主题 token 的名字**,不是一个写死的颜色 —— 值在 tokens.css(浅 / 深各一套)。
    expect(MASK_TINT_TOKEN).toMatch(/^--[a-z-]+$/);
  });

  /**
   * 着色那一层的颜色**就是传进来的那个**:这个函数不碰 DOM、也没有自己的红。
   * 两种颜色各断言一次(浅色 / 深色),第二遍顺带证明它不是哪个写死的字面量。
   */
  it("层表上的颜色 = 调用方传进来的那个(浅色主题)", () => {
    expect(shown(LIGHT_TINT)[2].tint).toBe(LIGHT_TINT);
  });

  it("换一个颜色(深色主题)层表跟着换 —— 颜色不是这张表里的常量", () => {
    expect(shown(DARK_TINT)[2].tint).toBe(DARK_TINT);
    expect(shown(DARK_TINT)[2].tint).not.toBe(shown(LIGHT_TINT)[2].tint);
  });

  it("「显示底图」关掉:只剩蒙版本身,一张和导出的那张一样的黑白视图", () => {
    expect(maskViewLayers({ hasUnderlay: true, showUnderlay: false, tint: LIGHT_TINT })).toEqual([
      { of: "mask", op: "source-over", alpha: 1 },
    ]);
  });

  it("开关真的换了一层表 —— 空转的开关就是关掉再打开屏幕一个像素都不动", () => {
    expect(maskViewLayers({ hasUnderlay: true, showUnderlay: true, tint: LIGHT_TINT })).not.toEqual(
      maskViewLayers({ hasUnderlay: true, showUnderlay: false, tint: LIGHT_TINT }),
    );
  });

  it("没有底图(读图失败、断网)时也是只剩蒙版,这时开关说了不算", () => {
    for (const showUnderlay of [true, false]) {
      expect(maskViewLayers({ hasUnderlay: false, showUnderlay, tint: LIGHT_TINT })).toEqual([
        { of: "mask", op: "source-over", alpha: 1 },
      ]);
    }
  });

  it("每一层的 alpha 都是 0..1 里的明确数字(漏了 globalAlpha 就是 1 或者 undefined)", () => {
    for (const layer of shown()) {
      expect(layer.alpha).toBeGreaterThan(0);
      expect(layer.alpha).toBeLessThanOrEqual(1);
    }
  });
});
