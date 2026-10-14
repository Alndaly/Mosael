import { describe, expect, it } from "vitest";

import {
  MAX_SCALE,
  clampPan,
  fitCamera,
  minScale,
  panBy,
  placement,
  toDoc,
  visiblePart,
  wheelIntent,
  zoomAround,
  zoomFactor,
} from "./maskCamera";

const doc = { width: 1624, height: 2880 };
const box = { width: 800, height: 600 };

describe("画蒙版的相机", () => {
  it("适应窗口:按原始比例含进盒子、居中", () => {
    const camera = fitCamera(doc, box);
    expect(camera.scale).toBeCloseTo(600 / 2880);
    expect(camera.y).toBeCloseTo(0);
    expect(camera.x).toBeCloseTo((800 - 1624 * camera.scale) / 2);
    //: 宽高比不变:落到屏幕上的那块矩形和图同一个比例。
    const place = placement(camera, doc, 1);
    expect(place.width / place.height).toBeCloseTo(1624 / 2880);
  });

  it("以某点为锚缩放:锚点下面那个文档像素不动", () => {
    const camera = fitCamera(doc, box);
    const anchor = { x: 420, y: 333 };
    const before = toDoc(camera, anchor);
    const zoomed = zoomAround(camera, 3, anchor, doc, box);
    expect(zoomed.scale).toBeCloseTo(camera.scale * 3);
    const after = toDoc(zoomed, anchor);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it("缩放夹在 [适应窗口的四分之一, 32] 之间", () => {
    const camera = fitCamera(doc, box);
    expect(zoomAround(camera, 1e6, { x: 0, y: 0 }, doc, box).scale).toBe(MAX_SCALE);
    expect(zoomAround(camera, 1e-6, { x: 0, y: 0 }, doc, box).scale).toBeCloseTo(minScale(doc, box));
    expect(minScale(doc, box)).toBeCloseTo(camera.scale / 4);
    //: 小图:最小不会大过 1(放不下也能缩回 100%)。
    expect(minScale({ width: 10, height: 10 }, box)).toBe(1);
  });

  it("平移收边:图至少留 48px 在盒子里", () => {
    const camera = fitCamera(doc, box);
    const far = panBy(camera, 10_000, 10_000, doc, box);
    expect(far.x).toBe(800 - 48);
    expect(far.y).toBe(600 - 48);
    const away = panBy(camera, -10_000, -10_000, doc, box);
    expect(away.x + 1624 * away.scale).toBeCloseTo(48);
    //: 已经在界内的不动。
    expect(clampPan(camera, doc, box)).toEqual(camera);
  });

  it("屏幕点 → 文档点:(屏幕 − 偏移) / 缩放", () => {
    expect(toDoc({ scale: 2, x: 10, y: -20 }, { x: 30, y: 0 })).toEqual({ x: 10, y: 10 });
  });

  it("只画看得见的那一块:放大之后派生层不按整张图分配", () => {
    const bitmap = { width: 800, height: 600 };
    const place = placement({ scale: 16, x: -4000, y: -8000 }, doc, 1);
    const part = visiblePart(place, bitmap)!;
    expect(part.target).toEqual({ x: 0, y: 0, width: 800, height: 600 });
    expect(part.fraction.x).toBeCloseTo(4000 / (1624 * 16));
    expect(part.fraction.width).toBeCloseTo(800 / (1624 * 16));
    //: 整块在外面:什么都不画。
    expect(visiblePart({ x: 900, y: 0, width: 100, height: 100 }, bitmap)).toBeNull();
  });

  it("滚轮跟着画布操控方式走:触控板滑动平移、捏合缩放;鼠标滚轮缩放、Shift 横移", () => {
    const wheel = { deltaX: 3, deltaY: 40, deltaMode: 0, ctrlKey: false, metaKey: false, shiftKey: false };
    expect(wheelIntent(wheel, "trackpad", 600)).toEqual({ kind: "pan", dx: -3, dy: -40 });
    expect(wheelIntent({ ...wheel, ctrlKey: true }, "trackpad", 600)).toEqual({ kind: "zoom", factor: zoomFactor(40) });
    expect(wheelIntent(wheel, "mouse", 600)).toEqual({ kind: "zoom", factor: zoomFactor(40) });
    expect(wheelIntent({ ...wheel, shiftKey: true }, "mouse", 600)).toEqual({ kind: "pan", dx: -40, dy: 0 });
    //: 行模式换成像素(× 16)。
    expect(wheelIntent({ ...wheel, deltaMode: 1 }, "trackpad", 600)).toEqual({ kind: "pan", dx: -48, dy: -640 });
    //: 往下滚是缩小;单次封顶。
    expect(zoomFactor(40)).toBeLessThan(1);
    expect(zoomFactor(-40)).toBeGreaterThan(1);
    expect(zoomFactor(-10_000)).toBeCloseTo(Math.E);
  });
});
