import { describe, expect, it } from "vitest";

import { visibleCanvasSize } from "./fitCanvasViewport";

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
