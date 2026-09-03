import { describe, expect, it } from "vitest";

import { readClipAppearance } from "./clipAppearance";

describe("readClipAppearance", () => {
  it("validates masks and shadows from clip effects", () => {
    expect(
      readClipAppearance({
        appearance: {
          mask: { shape: "circle", radius: 99 },
          shadow: {
            enabled: true,
            color: "#123456",
            opacity: 0.65,
            blur: 32,
            offset_x: 12,
            offset_y: -8,
          },
        },
      }),
    ).toEqual({
      mask: { shape: "circle", radius: 0.5 },
      shadow: { enabled: true, color: "#123456", opacity: 0.65, blur: 32, offsetX: 12, offsetY: -8 },
    });
  });

  it("falls back safely for old or malformed projects", () => {
    expect(readClipAppearance(undefined)).toEqual({
      mask: { shape: "none", radius: 0 },
      shadow: { enabled: false, color: "#000000", opacity: 0.4, blur: 24, offsetX: 0, offsetY: 12 },
    });
    expect(readClipAppearance({ appearance: { mask: { shape: "star" }, shadow: { color: "oops" } } })).toEqual({
      mask: { shape: "none", radius: 0 },
      shadow: { enabled: false, color: "#000000", opacity: 0.4, blur: 24, offsetX: 0, offsetY: 12 },
    });
  });
});
