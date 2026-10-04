/**
 * 截图几何(三种模式):整页长图截到哪、按多大比例出图,框选的比例对应原图哪几个像素。
 *
 * 错一条的后果是看得见的:框的是这一块截出来是另一块,超长页面截出一片空白。
 */
import { describe, expect, it } from "vitest";

import { MAX_CAPTURE_EDGE, MAX_FULL_PAGE_HEIGHT, planClip, planFullPage, regionCropRect } from "./pageToolsCore";

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

  it("截一块(元素 / 可见区域):左上、右下两条边各自换算成出图像素再取整,宽高用两条边相减 —— 不多带一行邻居", () => {
    // 元素在小数坐标上(实测:37.75, 613.25,200.5×80.25,2 倍屏)。此前起点在 CSS 像素里向下取整、终点向上取整,
    // 边上就多带进半个 CSS 像素 = 一整行设备像素的外圈颜色。
    const plan = planClip({ x: 37.75, y: 613.25, width: 200.5, height: 80.25 }, 2)!;
    // 两条边:x 75.5→76、476.5→477;y 1226.5→1227、1387→1387。宽 401、高 160 —— 正是元素自己。
    expect(plan.crop).toEqual({ x: 0, y: 1, width: 401, height: 160 });
    // 交给 CDP 的是盖住它的整数 CSS 区域(CDP 会把小数宽高截成整数,所以多截一点再按设备像素裁)。
    expect(plan.clip).toEqual({ x: 38, y: 613, width: 201, height: 81, scale: 1 });
    expect(plan.clip.width * 2).toBeGreaterThanOrEqual(plan.crop.x + plan.crop.width);
    expect(plan.clip.height * 2).toBeGreaterThanOrEqual(plan.crop.y + plan.crop.height);
    expect(plan.truncated).toBe(false);
  });

  it("截一块:边落在整数和半像素上时一像素不差;1 倍屏同样按两条边算", () => {
    expect(planClip({ x: 40, y: 600, width: 200, height: 80 }, 2)!.crop).toEqual({ x: 0, y: 0, width: 400, height: 160 });
    expect(planClip({ x: 40.5, y: 600.5, width: 200, height: 80 }, 2)!.crop).toEqual({ x: 1, y: 1, width: 400, height: 160 });
    expect(planClip({ x: 16, y: 1647.5, width: 1248, height: 436 }, 2)!.crop).toEqual({ x: 0, y: 1, width: 2496, height: 872 });
    expect(planClip({ x: 10.4, y: 20.6, width: 30.2, height: 10.1 }, 1)).toEqual({
      clip: { x: 10, y: 21, width: 31, height: 10, scale: 1 },
      crop: { x: 0, y: 0, width: 31, height: 10 },
      truncated: false,
    });
  });

  it("截一块:页面报来的设备像素比带着浮点误差(1.9999998807907104)时照样按 2 算,不因此错开一行", () => {
    // 实跑:面板里的缩放存成 0.30000001,换回原清晰度后页面读到的是 1.99999988 —— 37.75 × 它 = 75.49999,
    // 就近取整成了 75 而不是 76,左边、顶边各带进一行外圈。
    expect(planClip({ x: 37.75, y: 613.25, width: 200.5, height: 80.25 }, 1.9999998807907104)).toEqual(
      planClip({ x: 37.75, y: 613.25, width: 200.5, height: 80.25 }, 2),
    );
    expect(planFullPage({ width: 1280, height: 4200 }, { width: 1280, height: 800 }, 2.0000000794)).toEqual(
      planFullPage({ width: 1280, height: 4200 }, { width: 1280, height: 800 }, 2),
    );
  });

  it("截一块:缩到 0.3 的面板页面按屏幕的设备像素比算(截图那一下按原清晰度渲染,见 pageCapture)", () => {
    // 面板里页面读到的设备像素比是 2 × 0.3 = 0.6;截图时临时按屏幕的 2 渲染,几何就按 2 算。
    const zoomed = planClip({ x: 77.75, y: 193.25, width: 260.5, height: 80.25 }, 0.6 / 0.3)!;
    expect(zoomed.crop.width).toBe(521);
    expect(zoomed.crop.height).toBe(160);
    expect(zoomed.clip.scale).toBe(1);
  });

  it("截一块:没有大小的(被藏起来的元素)不截;比整页上限还高的只截上面一段,比例压到装得进纹理", () => {
    expect(planClip({ x: 5, y: 5, width: 0, height: 20 }, 2)).toBeNull();
    expect(planClip({ x: 5, y: 5, width: 0.2, height: 20 }, 2)).toBeNull();
    const tall = planClip({ x: 0, y: 0, width: 600, height: 40_000 }, 2)!;
    expect(tall.truncated).toBe(true);
    expect(tall.clip.scale).toBeLessThan(1);
    expect(tall.clip.height).toBeLessThanOrEqual(MAX_FULL_PAGE_HEIGHT + 1);
    expect(tall.clip.height * tall.clip.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE + 2);
    expect(tall.crop.height).toBeLessThanOrEqual(Math.ceil(tall.clip.height * tall.clip.scale * 2));
  });

  it("整页长图:装不进一张纹理时压比例,两条边都装得下", () => {
    const tall = planFullPage({ width: 1280, height: 90_000 }, { width: 1280, height: 800 }, 2);
    expect(tall.height * tall.scale * 2).toBeLessThanOrEqual(MAX_CAPTURE_EDGE);
    expect(tall.scale).toBeLessThan(1);
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
