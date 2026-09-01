import { describe, expect, it } from "vitest";

import { scaledCropRect } from "../src/capture";


describe("scaledCropRect", () => {
  it("maps CSS video coordinates onto the captured bitmap", () => {
    expect(
      scaledCropRect(
        { left: 100, top: 50, width: 640, height: 360, viewportWidth: 1280, viewportHeight: 720 },
        { width: 2560, height: 1440 },
      ),
    ).toEqual({ x: 200, y: 100, width: 1280, height: 720 });
  });
});
