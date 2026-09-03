import { describe, expect, it, vi } from "vitest";

import { DEFAULT_CLIP_APPEARANCE } from "../clipAppearance";
import { paintScene, type ScenePaintLayer } from "./scenePaint";

function context() {
  return {
    clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), translate: vi.fn(), rotate: vi.fn(), scale: vi.fn(),
    drawImage: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), roundRect: vi.fn(), arc: vi.fn(), fill: vi.fn(), clip: vi.fn(),
    globalAlpha: 1, filter: "none", fillStyle: "", shadowColor: "", shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
  };
}

const baseLayer = (): ScenePaintLayer => ({
  img: {} as CanvasImageSource,
  mw: 1600,
  mh: 900,
  tf: { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 },
  filter: "",
  isBase: false,
  appearance: DEFAULT_CLIP_APPEARANCE,
});

describe("paintScene clip appearance", () => {
  it("centre-crops a true circle instead of stretching the video into an ellipse", () => {
    const ctx = context();
    const layer = baseLayer();
    layer.appearance = { ...layer.appearance, mask: { shape: "circle", radius: 0.5 } };

    paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width: 800, height: 450, fillMode: "cover" });

    expect(ctx.arc).toHaveBeenCalledWith(0, 0, 225, 0, Math.PI * 2);
    expect(ctx.clip).toHaveBeenCalledTimes(1);
    expect(ctx.drawImage).toHaveBeenCalledWith(layer.img, 350, 0, 900, 900, -225, -225, 450, 450);
  });

  it("draws a shadow behind the masked shape", () => {
    const ctx = context();
    const layer = baseLayer();
    layer.appearance = {
      mask: { shape: "rounded", radius: 0.2 },
      shadow: { enabled: true, color: "#123456", opacity: 0.6, blur: 20, offsetX: 5, offsetY: 7 },
    };
    ctx.fill.mockImplementationOnce(() => {
      expect(ctx.shadowColor).toBe("rgba(18, 52, 86, 0.6)");
      expect(ctx.shadowBlur).toBe(20);
      expect(ctx.shadowOffsetX).toBe(5);
      expect(ctx.shadowOffsetY).toBe(7);
    });

    paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width: 800, height: 450, fillMode: "cover" });

    expect(ctx.roundRect).toHaveBeenCalled();
    expect(ctx.fill).toHaveBeenCalledTimes(1);
  });
});
