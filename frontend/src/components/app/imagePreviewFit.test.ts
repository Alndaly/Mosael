import { describe, expect, it } from "vitest";

import { fitVideo, imageFit } from "./image-preview";

describe("大图收进同一圈边距(上 64 下 64,左右 32)", () => {
  it("铺满高度的图缩到让出顶上那一条和底下的标题;视口越矮缩得越多", () => {
    expect(imageFit({ width: 2000, height: 1300 })).toBeCloseTo((1300 - 128) / 1300);
    expect(imageFit({ width: 800, height: 600 })).toBeCloseTo((600 - 128) / 600);
  });

  it("窄而高的视口按宽算;量不出视口就不缩", () => {
    expect(imageFit({ width: 400, height: 2000 })).toBeCloseTo((400 - 64) / 400);
    expect(imageFit({ width: 0, height: 0 })).toBe(1);
  });

  it("视频走的是同一圈边距:铺满高度的片子上下各让 64", () => {
    expect(fitVideo({ width: 1000, height: 1000 }, { width: 2000, height: 1300 })).toEqual({ width: 1172, height: 1172 });
  });
});
