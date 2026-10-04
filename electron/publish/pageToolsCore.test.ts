/**
 * 截图几何(三种模式):整页长图截到哪、按多大比例出图,框选的比例对应原图哪几个像素。
 *
 * 错一条的后果是看得见的:框的是这一块截出来是另一块,超长页面截出一片空白。
 */
import { describe, expect, it } from "vitest";

import { MAX_CAPTURE_EDGE, MAX_FULL_PAGE_HEIGHT, cdpClip, planClip, planFullPage, regionCropRect } from "./pageToolsCore";

describe("截图几何", () => {
  it("整页长图:截整页高度、可见区宽度,按屏幕原生清晰度出图(CDP 的 scale 乘在设备像素比上,所以是 1)", () => {
    expect(planFullPage({ width: 1280, height: 4200 }, { width: 1280, height: 800 }, 2)).toEqual({
      width: 1280,
      height: 4200,
      scale: 1,
      truncated: false,
    });
  });

  it("整页长图:内容比视口还矮(滚动在内层容器里)时按可见区高度截", () => {
    expect(planFullPage({ width: 1280, height: 300 }, { width: 1280, height: 800 }, 1).height).toBe(800);
  });

  it("整页长图:超过上限只截前面一段并如实标出,比例压到能装进一张纹理", () => {
    const plan = planFullPage({ width: 1280, height: 90_000 }, { width: 1280, height: 800 }, 2);
    expect(plan.height).toBe(MAX_FULL_PAGE_HEIGHT);
    expect(plan.truncated).toBe(true);
    // 出图像素 = CSS 像素 × scale × 设备像素比,两条边都得装进一张纹理。
    expect(plan.height * plan.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE);
    expect(plan.width * plan.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE);
    expect(plan.scale).toBeLessThan(1);
  });

  it("页面缩放过(悬浮面板里的自动化会话):坐标乘上缩放、scale 除回去,出图和没缩放时一样大一样清楚", () => {
    // 面板把网页缩到 0.3:页面里读到的设备像素比是 2 × 0.3 = 0.6。CDP 的 clip 量的是缩放之后的像素,
    // scale 乘的是屏幕的 2(实测直接按 CSS 坐标截,网页只占左上角三成、元素截出来一片白)。
    const plan = planClip({ x: 0, y: 1600, width: 1280, height: 436 }, 0.6, 0.3)!;
    expect(plan.clip.x).toBe(0);
    expect(plan.clip.y).toBeCloseTo(480, 6);
    expect(plan.clip.width).toBeCloseTo(384, 6);
    expect(plan.clip.scale).toBeCloseTo(1 / 0.3, 6);
    // 出图像素 = clip 宽 × scale × 屏幕的 2 = CSS 宽 × 2。
    expect(plan.clip.width * plan.clip.scale * 2).toBeCloseTo(1280 * 2, 6);
    expect(cdpClip({ x: 10, y: 20, width: 30, height: 40 }, 0.5, 1)).toEqual({ x: 10, y: 20, width: 30, height: 40, scale: 0.5 });
  });

  it("页面缩放过的整页长图:装纹理按屏幕的设备像素比算", () => {
    expect(planFullPage({ width: 1280, height: 3000 }, { width: 1280, height: 800 }, 0.6, 0.3).scale).toBe(1);
    const tall = planFullPage({ width: 1280, height: 90_000 }, { width: 1280, height: 800 }, 0.6, 0.3);
    expect(tall.height * tall.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE);
    expect(tall.scale).toBeLessThan(1);
  });

  it("截一块(可见区域、某个元素):取整到像素,文档坐标原样带上,比例同整页", () => {
    expect(planClip({ x: 10.4, y: 1200.6, width: 300.2, height: 199.1 }, 2)).toEqual({
      clip: { x: 10, y: 1200, width: 301, height: 200, scale: 1 },
      truncated: false,
    });
  });

  it("截一块:没有大小的(被藏起来的元素)不截;比整页上限还高的只截上面一段", () => {
    expect(planClip({ x: 5, y: 5, width: 0, height: 20 }, 2)).toBeNull();
    const tall = planClip({ x: 0, y: 0, width: 600, height: 40_000 }, 2)!;
    expect(tall.truncated).toBe(true);
    expect(tall.clip.height).toBe(MAX_FULL_PAGE_HEIGHT);
    expect(tall.clip.height * tall.clip.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE);
  });

  it("框选:比例换算成原图像素,与界面显示的缩放无关", () => {
    // 2560×1600 的高分屏截图,界面上缩成一半显示;框的是画面中间那块。
    expect(regionCropRect({ x: 0.25, y: 0.25, width: 0.5, height: 0.5 }, { width: 2560, height: 1600 })).toEqual({
      x: 640,
      y: 400,
      width: 1280,
      height: 800,
    });
  });

  it("框选:反方向拖出来的框照样认,拖出画面的部分夹回来", () => {
    expect(regionCropRect({ x: 0.9, y: 0.5, width: -0.4, height: 0.8 }, { width: 1000, height: 1000 })).toEqual({
      x: 500,
      y: 500,
      width: 400,
      height: 500,
    });
  });

  it("框选:框得太小(手一抖的单击)当作没框", () => {
    expect(regionCropRect({ x: 0.5, y: 0.5, width: 0.001, height: 0.2 }, { width: 1280, height: 800 })).toBeNull();
  });
});
