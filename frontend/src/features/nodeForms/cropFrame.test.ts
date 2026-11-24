import { describe, expect, it } from "vitest";

import {
  cropPatch,
  cropPixels,
  dragCrop,
  fitAspect,
  fractionRatio,
  matchingAspect,
  MIN_FRACTION,
  readCrop,
  WHOLE,
} from "@/features/nodeForms/cropFrame";

describe("裁切框(ADR 0110)", () => {
  it("没写、写错的按整张,超出的夹进图里;写回四位小数", () => {
    expect(readCrop({})).toEqual(WHOLE);
    expect(readCrop({ crop_x: "不是数", crop_width: null })).toEqual(WHOLE);
    expect(readCrop({ crop_x: 0.8, crop_y: -1, crop_width: 0.5, crop_height: 3 })).toEqual({ x: 0.8, y: 0, width: expect.closeTo(0.2), height: 1 });
    expect(cropPatch({ x: 1 / 3, y: 0, width: 0.5, height: 2 / 3 })).toEqual({ crop_x: 0.3333, crop_y: 0, crop_width: 0.5, crop_height: 0.6667 });
  });

  it("比例按原图的宽高比折过来:16:9 的图上 16:9 就是整张,1:1 是居中的一块", () => {
    const wide = 16 / 9;
    expect(fitAspect(fractionRatio("16:9", wide)!)).toEqual(WHOLE);
    const square = fitAspect(fractionRatio("1:1", wide)!);
    expect(square.height).toBe(1);
    expect(square.width).toBeCloseTo(9 / 16);
    expect(square.x).toBeCloseTo((1 - 9 / 16) / 2);
    expect(fractionRatio("original", wide)).toBe(1);
    expect(fractionRatio("free", wide)).toBeNull();
    expect(matchingAspect(square, wide)).toBe("1:1");
    expect(matchingAspect({ x: 0, y: 0, width: 0.3, height: 0.7 }, wide)).toBe("free");
  });

  it("挪:整框跟着走、不出图", () => {
    const box = { x: 0.2, y: 0.2, width: 0.5, height: 0.5 };
    expect(dragCrop(box, "move", 0.1, -0.05, null)).toEqual({ x: expect.closeTo(0.3), y: expect.closeTo(0.15), width: 0.5, height: 0.5 });
    expect(dragCrop(box, "move", 1, 1, null)).toEqual({ x: 0.5, y: 0.5, width: 0.5, height: 0.5 });
  });

  it("改大小:对边不动、不小于下限、不出图", () => {
    const box = { x: 0.2, y: 0.2, width: 0.5, height: 0.5 };
    const grown = dragCrop(box, "se", 0.1, 0.1, null);
    expect(grown).toEqual({ x: 0.2, y: 0.2, width: expect.closeTo(0.6), height: expect.closeTo(0.6) });
    const squeezed = dragCrop(box, "w", 0.9, 0, null);
    expect(squeezed.width).toBeCloseTo(MIN_FRACTION);
    expect(squeezed.x + squeezed.width).toBeCloseTo(0.7);
    expect(dragCrop(box, "n", 0, -1, null)).toEqual({ x: 0.2, y: 0, width: expect.closeTo(0.5), height: expect.closeTo(0.7) });
  });

  it("锁着比例:角上按宽算高、对角不动;边上另一维以中线为准;放不下时两维一起收", () => {
    const box = { x: 0.25, y: 0.25, width: 0.5, height: 0.5 };
    const corner = dragCrop(box, "se", 0.1, 0.4, 1);
    expect(corner.width / corner.height).toBeCloseTo(1);
    expect(corner.x).toBeCloseTo(0.25);
    expect(corner.y).toBeCloseTo(0.25);
    expect(corner.width).toBeCloseTo(0.6);
    const edge = dragCrop(box, "e", 0.1, 0, 1);
    expect(edge.width).toBeCloseTo(0.6);
    expect(edge.y + edge.height / 2).toBeCloseTo(0.5);
    const huge = dragCrop(box, "se", 2, 2, 1);
    expect(huge.x + huge.width).toBeLessThanOrEqual(1 + 1e-9);
    expect(huge.y + huge.height).toBeLessThanOrEqual(1 + 1e-9);
    expect(huge.width / huge.height).toBeCloseTo(1);
  });

  it("读数是切出来的像素", () => {
    expect(cropPixels({ x: 0, y: 0, width: 0.5, height: 0.25 }, { width: 1920, height: 1080 })).toEqual({ width: 960, height: 270 });
    expect(cropPixels(WHOLE, null)).toBeNull();
  });
});
