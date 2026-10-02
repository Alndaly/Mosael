/**
 * 片段投影:预览和导出必须是同一种语义 —— 偏移与模糊按**画面像素**,不随片段的缩放、旋转变。
 *
 * 语料是两侧共用的一份(contracts/clip-shadow-cases.json),后端 tests/test_clip_shadow_parity.py 真渲一帧、
 * 从像素里量回偏移和 σ。这里断言 paintScene 让 canvas 把投影画在哪、糊多少:canvas 的 shadowOffset 是
 * 画布像素(不受当前变换影响),σ = shadowBlur / 2(HTML 规范,Chromium 实测一致)。
 *
 * 量法不看「shadowOffsetX 写了几」,而是跟着变换矩阵算:剪影在画布上的中心 + shadowOffset = 影子的中心,
 * 减去媒体在画布上的中心,就是用户看到的偏移。这样不管 paintScene 用什么手法画影子,量的都是结果。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { DEFAULT_CLIP_APPEARANCE } from "../clipAppearance";
import { paintScene, type ScenePaintLayer } from "./scenePaint";

const path = fileURLToPath(new URL("../../../../../contracts/clip-shadow-cases.json", import.meta.url));
const contract = JSON.parse(readFileSync(path, "utf8")) as {
  contract: string;
  version: number;
  frame: { width: number; height: number };
  cases: Array<{
    name: string;
    transform: { scale: number; rotation: number };
    shadow: { blur: number; offset_x: number; offset_y: number };
    expected: { offset_px: { x: number; y: number }; sigma_px: number };
  }>;
};

type Matrix = [number, number, number, number, number, number];
type Point = { x: number; y: number };

const apply = ([a, b, c, d, e, f]: Matrix, { x, y }: Point): Point => ({ x: a * x + c * y + e, y: b * x + d * y + f });
const multiply = ([a, b, c, d, e, f]: Matrix, [a2, b2, c2, d2, e2, f2]: Matrix): Matrix => [
  a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f,
];

/** 一块会记变换矩阵的假 canvas:fill 时记下剪影的四个角(画布坐标)和投影参数,drawImage 时记下媒体的中心。 */
function recordingContext() {
  let matrix: Matrix = [1, 0, 0, 1, 0, 0];
  const stack: Matrix[] = [];
  let path: Point[] = [];
  const fills: Array<{ corners: Point[]; offsetX: number; offsetY: number; blur: number }> = [];
  const draws: Point[] = [];
  const ctx = {
    globalAlpha: 1, filter: "none", fillStyle: "", shadowColor: "", shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    clearRect() {},
    save() { stack.push(matrix); },
    restore() { matrix = stack.pop() ?? [1, 0, 0, 1, 0, 0]; },
    translate(x: number, y: number) { matrix = multiply(matrix, [1, 0, 0, 1, x, y]); },
    rotate(angle: number) { matrix = multiply(matrix, [Math.cos(angle), Math.sin(angle), -Math.sin(angle), Math.cos(angle), 0, 0]); },
    scale(x: number, y: number) { matrix = multiply(matrix, [x, 0, 0, y, 0, 0]); },
    beginPath() { path = []; },
    rect(x: number, y: number, w: number, h: number) {
      path = [{ x, y }, { x: x + w, y }, { x, y: y + h }, { x: x + w, y: y + h }].map((one) => apply(matrix, one));
    },
    roundRect(x: number, y: number, w: number, h: number) { ctx.rect(x, y, w, h); },
    arc(x: number, y: number, r: number) { ctx.rect(x - r, y - r, 2 * r, 2 * r); },
    fill() { fills.push({ corners: path, offsetX: ctx.shadowOffsetX, offsetY: ctx.shadowOffsetY, blur: ctx.shadowBlur }); },
    clip() {},
    drawImage(...args: number[]) {
      const [dx, dy, dw, dh] = args.length === 9 ? args.slice(5) : args.slice(1);
      draws.push(apply(matrix, { x: dx + dw / 2, y: dy + dh / 2 }));
    },
  };
  return { ctx, fills, draws };
}

const center = (corners: Point[]): Point => ({
  x: corners.reduce((sum, one) => sum + one.x, 0) / corners.length,
  y: corners.reduce((sum, one) => sum + one.y, 0) / corners.length,
});

describe("片段投影 · 前后端共用语料", () => {
  it("语料在,且带版本", () => {
    expect(contract.contract).toBe("clip-shadow");
    expect(contract.version).toBe(1);
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  for (const one of contract.cases) {
    it(one.name, () => {
      const { width, height } = contract.frame;
      const { ctx, fills, draws } = recordingContext();
      const layer: ScenePaintLayer = {
        img: {} as CanvasImageSource,
        mw: width,
        mh: height,
        tf: { scale: one.transform.scale, x: 0, y: 0, rotation: one.transform.rotation, opacity: 1 },
        filter: "",
        isBase: false,
        appearance: {
          ...DEFAULT_CLIP_APPEARANCE,
          shadow: {
            enabled: true, color: "#ffffff", opacity: 1, blur: one.shadow.blur,
            offsetX: one.shadow.offset_x, offsetY: one.shadow.offset_y,
          },
        },
      };

      paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width, height, fillMode: "cover" });

      expect(fills).toHaveLength(1);
      expect(draws).toHaveLength(1);
      const [silhouette] = fills;
      const shadowAt = center(silhouette.corners);
      const offset = { x: shadowAt.x + silhouette.offsetX - draws[0].x, y: shadowAt.y + silhouette.offsetY - draws[0].y };
      expect(offset.x).toBeCloseTo(one.expected.offset_px.x, 6);
      expect(offset.y).toBeCloseTo(one.expected.offset_px.y, 6);
      expect(silhouette.blur / 2).toBeCloseTo(one.expected.sigma_px, 6);
      // 剪影本身不在画面里:只有影子落进来。剪影留在元素底下的话,片段半透明时它会透上来。
      expect(silhouette.corners.every((corner) => corner.x < 0)).toBe(true);
    });
  }
});
