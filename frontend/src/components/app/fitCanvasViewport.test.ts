import { describe, expect, it, vi } from "vitest";

import type { ReactFlowInstance } from "@xyflow/react";
import { centerCanvasViewport, excludeCanvasOverlay, visibleCanvasSize } from "./fitCanvasViewport";

describe("visibleCanvasSize", () => {
  it("removes docked overlays from the fit viewport", () => {
    expect(visibleCanvasSize(1200, 800, { top: 58, right: 424, bottom: 8 })).toEqual({
      left: 0,
      top: 58,
      width: 776,
      height: 734,
    });
  });

  it("never produces a non-positive viewport", () => {
    expect(visibleCanvasSize(100, 80, { right: 200, bottom: 100 })).toMatchObject({ width: 1, height: 1 });
  });
});


describe("centerCanvasViewport", () => {
  it.each([
    { right: 0, zoom: 1 },
    { right: 416, zoom: 0.6 },
    { right: 656, zoom: 1.5 },
  ])("centers in visible space with dock $right and zoom $zoom", ({ right, zoom }) => {
    const setViewport = vi.fn();
    const instance = { setViewport, getZoom: () => zoom } as unknown as ReactFlowInstance;
    const surface = { clientWidth: 1200, clientHeight: 800 } as HTMLElement;
    const point = { x: 900, y: 420 };
    centerCanvasViewport(instance, surface, point, { right }, { duration: 0 });
    const transform = setViewport.mock.calls[0][0];
    expect(point.x * zoom + transform.x).toBeCloseTo((1200 - right) / 2);
    expect(point.y * zoom + transform.y).toBeCloseTo(400);
    expect(setViewport.mock.calls[0][1]).toEqual({ duration: 0 });
  });

  it("uses current surface dimensions and insets when a dock resizes or closes", () => {
    const setViewport = vi.fn();
    const instance = { setViewport, getZoom: () => 1 } as unknown as ReactFlowInstance;
    const surface = { clientWidth: 1200, clientHeight: 800 } as HTMLElement;
    for (const right of [416, 656, 0]) {
      centerCanvasViewport(instance, surface, { x: 100, y: 200 }, { left: 20, top: 50, right, bottom: 10 });
      const transform = setViewport.mock.lastCall![0];
      expect(100 + transform.x).toBe((1200 + 20 - right) / 2);
      expect(200 + transform.y).toBe(420);
    }
  });
});


describe("excludeCanvasOverlay", () => {
  it("centers in the larger clear area beside a floating assistant", () => {
    expect(excludeCanvasOverlay(1200, 800, {}, { left: 800, top: 100, right: 1180, bottom: 780 }))
      .toEqual({ left: 0, top: 0, right: 408, bottom: 0 });
    expect(excludeCanvasOverlay(1200, 800, {}, { left: 10, top: 100, right: 400, bottom: 780 }))
      .toEqual({ left: 408, top: 0, right: 0, bottom: 0 });
  });
  it("respects the dock and ignores floating panels outside the visible area", () => {
    expect(excludeCanvasOverlay(1200, 800, { right: 416 }, { left: 900, top: 100, right: 1190, bottom: 790 }))
      .toEqual({ right: 416 });
  });
  it("can use the area below a shallow floating panel", () => {
    expect(excludeCanvasOverlay(1200, 800, {}, { left: 50, top: 10, right: 1150, bottom: 200 }))
      .toEqual({ left: 0, top: 208, right: 0, bottom: 0 });
  });
});
