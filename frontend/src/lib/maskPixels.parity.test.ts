/**
 * 蒙版形状运算的**前端一侧**:跑 contracts/mask-cases.json。
 *
 * 后端 `backend/tests/test_mask_parity.py` 读同一个文件,把同一串源图小样、同一组参数
 * (阈值 / 反选 / 扩张 / 羽化)再算一遍,拿**同一串期望字节**对 —— 逐字节。
 *
 * 为什么会漏掉:两侧各写了一句「逐位相等」(后端 `masks.py` 的文件头、本文件的 `Math.round`),
 * 却各测各的。后端那边的半径是 `int(round(radius))`(Python 的半数取偶:`round(0.5) == 0`、
 * `round(2.5) == 2`),这里是 `Math.round`(半数进位):`feather = 0.5` 时后端一格都不羽化、
 * 编辑器羽化了一格;`2.5` 一边 2 格一边 3 格 —— 同一组参数、两张图,而两侧的单元测试都还是绿的。
 * 语料里那几条 `.5` 就是入口。
 *
 * ADR 0057 起编辑器也做扩张 / 收缩(「应用到蒙版」那一步,先扩张再羽化),所以这里跑**全部**用例,
 * 两张取整表(`rounding` 按 feather、`grow_rounding` 按 grow)都读。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  alphaMask,
  discSegments,
  featherMask,
  grayscaleOf,
  growMask,
  invertMask,
  isOpaque,
  thresholdMask,
  type MaskPixels,
} from "@/lib/maskPixels";

interface MaskCase {
  name: string;
  note: string;
  source: string;
  source_kind: "luminance" | "alpha";
  threshold: number;
  invert: boolean;
  grow: number;
  feather: number;
  expected_reach: number;
  expected_grow_reach?: number;
  expected_hex: string;
}

const path = fileURLToPath(new URL("../../../contracts/mask-cases.json", import.meta.url));
const contract = JSON.parse(readFileSync(path, "utf8")) as {
  contract: string;
  version: number;
  frame: { width: number; height: number };
  sides: Record<string, string[]>;
  rounding: Array<{ feather: number; reach: number; note: string }>;
  grow_rounding: Array<{ grow: number; reach: number; note: string }>;
  sources: Record<string, { note: string; rgba_hex: string }>;
  cases: MaskCase[];
  disc: {
    note: string;
    exact: Array<{ r: number; shape: string; offsets: number[][]; note: string }>;
    octagons: Array<{ r: number; m: number; M: number; axis: number; diagonal: number }>;
  };
};

const { width, height } = contract.frame;

/** 语料里那份 RGBA 小样(第 i 个像素在第 4i 格,和 canvas 的 ImageData 一样)。 */
function rgba(one: MaskCase): MaskPixels {
  return new Uint8ClampedArray(Buffer.from(contract.sources[one.source].rgba_hex, "hex"));
}

/** 语料说的那四步,按定死的先后:阈值 → 反选 → 扩张/收缩 → 羽化。`grow` 可换成对照实现。 */
function pipeline(one: MaskCase, grow: typeof growMask = growMask): MaskPixels {
  const data = rgba(one);
  if (one.source_kind === "alpha") alphaMask(data, one.threshold);
  else thresholdMask(data, one.threshold);
  if (one.invert) invertMask(data);
  grow(data, width, height, one.grow);
  featherMask(data, width, height, one.feather);
  return data;
}

/**
 * **改之前**那一版结构元:`(2r+1)²` 的正方形窗口,每个取样点各自夹回图内。
 *
 * 只在小语料(7×5)上当对照用 —— "形状退回正方形时语料会不会红"靠它。
 */
function squareGrow(data: MaskPixels, w: number, h: number, radius: number): void {
  const reach = Math.min(Math.abs(Math.floor(radius + 0.5)), Math.max(w, h));
  const pick = radius > 0 ? Math.max : Math.min;
  const source = new Uint8ClampedArray(w * h);
  for (let i = 0; i < w * h; i += 1) source[i] = data[i * 4];
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let best = source[y * w + x];
      for (let dy = -reach; dy <= reach; dy += 1) {
        for (let dx = -reach; dx <= reach; dx += 1) {
          best = pick(best, source[Math.min(h - 1, Math.max(0, y + dy)) * w + Math.min(w - 1, Math.max(0, x + dx))]);
        }
      }
      data[(y * w + x) * 4] = best;
      data[(y * w + x) * 4 + 1] = best;
      data[(y * w + x) * 4 + 2] = best;
      data[(y * w + x) * 4 + 3] = 255;
    }
  }
}

/** 结构元的偏移集:组内闵可夫斯基和、组间取并 —— 语料 `disc` 那张表说的就是它。 */
function discOffsets(reach: number): Array<[number, number]> {
  const points = new Map<string, [number, number]>();
  for (const group of discSegments(reach)) {
    let acc: Array<[number, number]> = [[0, 0]];
    for (const [dx, dy, step] of group) {
      const next: Array<[number, number]> = [];
      for (const [x, y] of acc) for (let t = -step; t <= step; t += 1) next.push([x + t * dx, y + t * dy]);
      acc = next;
    }
    for (const point of acc) points.set(point.join(","), point);
  }
  return [...points.values()];
}

/** 一份前端算出来的蒙版 —— 单通道那一串字节(`r = g = b`,取红通道)。 */
function bytesOf(data: MaskPixels): string {
  return Buffer.from(grayscaleOf(data)).toString("hex");
}

describe("蒙版形状运算 · 前后端共用语料", () => {
  it("语料在,且带版本 —— 找不到就静默跳过是最坏的结果", () => {
    expect(contract.contract).toBe("mask-cases");
    expect(contract.version).toBe(1);
    expect(contract.cases.length).toBeGreaterThan(0);
    expect(contract.rounding.length).toBeGreaterThan(0);
    expect(contract.grow_rounding.length).toBeGreaterThan(0);
  });

  it("两侧是同一张表:前端也跑扩张 / 收缩", () => {
    expect(contract.sides["frontend/src/lib/maskPixels.ts"]).toEqual(["threshold", "invert", "grow", "feather"]);
    expect(contract.sides["frontend/src/lib/maskPixels.ts"]).toEqual(contract.sides["backend/app/media/masks.py"]);
    expect(contract.cases.some((one) => one.grow > 0)).toBe(true);
    expect(contract.cases.some((one) => one.grow < 0)).toBe(true);
  });

  for (const one of contract.cases) {
    it(one.name, () => {
      const data = pipeline(one);

      expect(bytesOf(data)).toBe(one.expected_hex);
      //: 交出去的是一张**灰度、不透明**的蒙版:带透明通道的图在插件那条路上读出来是整块不透明。
      expect(isOpaque(data)).toBe(true);
      for (let at = 0; at < data.length; at += 4) {
        expect([data[at + 1], data[at + 2]]).toEqual([data[at], data[at]]);
      }
    });
  }

  /** 语料第一条那条硬边(不扩张、不羽化):两张取整表都在它上面比。 */
  const base = () => pipeline({ ...contract.cases[0], grow: 0, feather: 0 });

  it("羽化半径按半数进位取整 —— 语料那张 rounding 表", () => {
    const feathered = (radius: number): MaskPixels => {
      const data = base();
      featherMask(data, width, height, radius);
      return data;
    };

    for (const one of contract.rounding) {
      expect([...feathered(one.feather)]).toEqual([...feathered(one.reach)]);
    }
    //: 这几条是**真的分岔**:`0.5` 按半数取偶是 0 格(原样),`2.5` 是 2 格 —— 语料能红靠的就是它们。
    expect([...feathered(0.5)]).not.toEqual([...base()]);
    expect([...feathered(2.5)]).not.toEqual([...feathered(2)]);
    expect([...feathered(4.5)]).not.toEqual([...feathered(4)]);
  });

  it("扩张半径也按半数进位取整 —— 语料那张 grow_rounding 表", () => {
    const grown = (radius: number): MaskPixels => {
      const data = base();
      growMask(data, width, height, radius);
      return data;
    };

    for (const one of contract.grow_rounding) {
      //: reach 是窗口半宽(取绝对值),方向看 grow 的符号。
      const signed = one.grow < 0 ? -one.reach : one.reach;
      expect([...grown(one.grow)], `${one.grow} → ${signed}`).toEqual([...grown(signed)]);
    }
    //: 向零截断(`Math.trunc`)在这几条上给的是另一格 —— 用例钉得住那次分岔。
    for (const radius of [0.5, 1.5, 2.5, -1.7]) {
      expect([...grown(radius)]).not.toEqual([...grown(Math.trunc(radius))]);
    }
    expect([...grown(0.4)]).toEqual([...base()]);
  });

  it("语料里那几条半数用例真的能分出两种取整", () => {
    //: `Math.round` 是半数进位;半数取偶是 Python 那边 `round` 的行为,这里手写一遍当对照。
    const halfEven = (value: number) => {
      const down = Math.floor(value);
      const up = down + 1;
      if (value - down !== 0.5) return Math.round(value);
      return down % 2 === 0 ? down : up;
    };
    const divergent = contract.rounding.filter((one) => halfEven(one.feather) !== Math.floor(one.feather + 0.5));
    expect(divergent.length).toBeGreaterThan(0);
    const used = new Set(contract.cases.map((one) => one.feather));
    for (const one of divergent) expect(used.has(one.feather)).toBe(true);
  });

  it("圆盘:半径到八边形参数那张表(disc)和实现一致", () => {
    //: r ≤ 2 是精确的数字圆盘:偏移集逐格对语料里那张表。
    expect(contract.disc.exact.length).toBeGreaterThan(0);
    for (const one of contract.disc.exact) {
      const got = discOffsets(one.r).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      const want = one.offsets.map(([x, y]) => [x, y]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      expect(got, `r=${one.r}`).toEqual(want);
    }
    //: r ≥ 3 是八边形:先核参数,再把小半径的偏移集和那个八边形的整点比一遍(大半径点太多)。
    for (const one of contract.disc.octagons) {
      const groups = discSegments(one.r);
      expect(groups.length, `r=${one.r} 该是一组(八边形)`).toBe(1);
      const axis = groups[0].filter(([dx, dy]) => dx === 0 || dy === 0).map(([, , step]) => step);
      const diagonal = groups[0].filter(([dx, dy]) => dx !== 0 && dy !== 0).map(([, , step]) => step);
      expect([...new Set(axis)]).toEqual([one.axis]);
      expect([...new Set(diagonal)]).toEqual([one.diagonal]);
      if (one.r > 20) continue;
      const want: Array<[number, number]> = [];
      for (let x = -one.r; x <= one.r; x += 1) {
        for (let y = -one.r; y <= one.r; y += 1) {
          if (Math.abs(x) <= one.r && Math.abs(x + y) <= one.M && Math.abs(x - y) <= one.M) want.push([x, y]);
        }
      }
      const got = discOffsets(one.r).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      expect(got, `r=${one.r}`).toEqual(want.sort((a, b) => a[0] - b[0] || a[1] - b[1]));
    }
  });

  it("语料里那几条扩张用例真的能分出圆盘与正方形", () => {
    //: 结构元退回正方形(改之前那一版)时语料必须红 —— 一条永远绿的语料比没有更糟。
    const diverged = contract.cases
      .filter((one) => one.grow && bytesOf(pipeline(one, squareGrow)) !== one.expected_hex)
      .map((one) => one.name);
    expect(diverged.length, `能分出圆盘与正方形的用例:${diverged.join("、")}`).toBeGreaterThanOrEqual(3);
  });
});
