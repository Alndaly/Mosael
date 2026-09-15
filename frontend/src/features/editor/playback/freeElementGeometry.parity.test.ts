/**
 * 自由元素(带蒙版/阴影的片段)的几何:预览和导出必须算出同一块。
 *
 * 这条对账语料是**两侧共用**的一份(contracts/clip-free-element-geometry.json),后端
 * tests/test_free_element_geometry_parity.py 跑同一份。各写一遍的结果已经见过两次:
 * 先是圆的大小差 1.78 倍,修好大小之后圆里的**内容**又差 1.78 倍 —— 两次都要等到看成片才发现,
 * 而单元测试的素材恰好和画幅同比例(那一档两种写法都对),所以一次都没拦住。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_CLIP_APPEARANCE } from "../clipAppearance";
import { paintScene, type ScenePaintLayer } from "./scenePaint";

const path = fileURLToPath(new URL("../../../../../contracts/clip-free-element-geometry.json", import.meta.url));
const contract = JSON.parse(readFileSync(path, "utf8")) as {
  contract: string;
  version: number;
  cases: Array<{
    name: string;
    source: { width: number; height: number };
    frame: { width: number; height: number };
    circle: boolean;
    expected: {
      element: { width: number; height: number };
      source_rect: { x: number; y: number; width: number; height: number };
    };
  }>;
};

function context() {
  return {
    clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), translate: vi.fn(), rotate: vi.fn(), scale: vi.fn(),
    drawImage: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), roundRect: vi.fn(), arc: vi.fn(), fill: vi.fn(), clip: vi.fn(),
    globalAlpha: 1, filter: "none", fillStyle: "", shadowColor: "", shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
  };
}

describe("自由元素几何 · 前后端共用语料", () => {
  it("语料在,且带版本", () => {
    expect(contract.contract).toBe("clip-free-element-geometry");
    expect(contract.version).toBe(1);
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  for (const one of contract.cases) {
    it(one.name, () => {
      const ctx = context();
      const layer: ScenePaintLayer = {
        img: {} as CanvasImageSource,
        mw: one.source.width,
        mh: one.source.height,
        tf: { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 },
        filter: "",
        isBase: false,
        appearance: one.circle
          ? { ...DEFAULT_CLIP_APPEARANCE, mask: { shape: "circle", radius: 0.5 } }
          // 只有阴影时也是自由元素 —— 这一档专门盯"不是圆也要按画幅裁"。
          : { mask: { shape: "none", radius: 0 },
              shadow: { enabled: true, color: "#000000", opacity: 0.5, blur: 8, offsetX: 0, offsetY: 0 } },
      };

      paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], {
        width: one.frame.width, height: one.frame.height, fillMode: "cover",
      });

      // 阴影那一档会先画一次剪影(fill),真正的媒体绘制是最后一次 drawImage。
      const call = ctx.drawImage.mock.calls.at(-1) as [unknown, number, number, number, number, number, number, number, number];
      const [, sx, sy, sw, sh, dx, dy, dw, dh] = call;
      const want = one.expected;
      expect({ sx, sy, sw, sh }).toEqual({
        sx: want.source_rect.x, sy: want.source_rect.y, sw: want.source_rect.width, sh: want.source_rect.height,
      });
      expect({ dw, dh }).toEqual({ dw: want.element.width, dh: want.element.height });
      // 元素以中心为原点绘制 —— transform 的平移/旋转/缩放都绕中心。
      expect({ dx, dy }).toEqual({ dx: -want.element.width / 2, dy: -want.element.height / 2 });
    });
  }
});
