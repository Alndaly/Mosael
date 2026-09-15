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

describe("自由元素的尺寸不跟着素材比例走", () => {
  // 导出那边是 `scale=W:H:force_original_aspect_ratio=increase,crop=W:H` —— **铺满再裁到画幅**,
  // 于是带蒙版/阴影的元素就是 W×H,和素材自身的宽高比无关。预览此前只铺满、不裁,拿的是
  // min(dw,dh);素材比例和画幅一致时两者相等(上面那条用例正是 1600×900 进 800×450),
  // 一旦不一致就分叉 —— 竖素材进横画幅差 1.78 倍,成片里的圆明显比预览小一圈。
  const portraitIntoLandscape = () => {
    const layer = baseLayer();
    layer.mw = 1080;
    layer.mh = 1920;
    return layer;
  };

  it("圆形蒙版的直径来自画幅的短边,不是素材铺满之后的短边", () => {
    const ctx = context();
    const layer = portraitIntoLandscape();
    layer.appearance = { ...layer.appearance, mask: { shape: "circle", radius: 0.5 } };

    paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width: 1920, height: 1080, fillMode: "cover" });

    // 画幅短边 1080 → 半径 540。按旧算法是 min(1920, 3413)=1920 → 半径 960。
    expect(ctx.arc).toHaveBeenCalledWith(0, 0, 540, 0, Math.PI * 2);
    expect(ctx.drawImage).toHaveBeenCalledWith(layer.img, 0, 420, 1080, 1080, -540, -540, 1080, 1080);
  });

  it("只有阴影(没有蒙版)时同样是画幅那么大,而且按画幅比例中心裁源", () => {
    const ctx = context();
    const layer = portraitIntoLandscape();
    layer.appearance = {
      mask: { shape: "none", radius: 0 },
      shadow: { enabled: true, color: "#000000", opacity: 0.5, blur: 10, offsetX: 0, offsetY: 0 },
    };

    paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width: 1920, height: 1080, fillMode: "cover" });

    // 16:9 的框从 1080×1920 的源里中心裁 1080×607.5,而不是把整张竖图塞进去(那会压扁)。
    expect(ctx.drawImage).toHaveBeenCalledWith(layer.img, 0, 656.25, 1080, 607.5, -960, -540, 1920, 1080);
  });

  it("没有蒙版也没有阴影的基础层不受影响 —— 它走的是画幅填充模式那条路", () => {
    const ctx = context();
    const layer = portraitIntoLandscape();
    layer.isBase = true;

    paintScene(ctx as unknown as CanvasRenderingContext2D, [layer], { width: 1920, height: 1080, fillMode: "cover" });

    // 基础层照旧把整张源铺满画幅(溢出的部分由画布自己裁掉),不走中心裁那条。
    const [img, x, y, w, h] = ctx.drawImage.mock.calls[0] as [unknown, number, number, number, number];
    expect(img).toBe(layer.img);
    expect(x).toBe(-960);
    expect(w).toBe(1920);
    expect(h).toBeCloseTo(3413.333, 2);
    expect(y).toBeCloseTo(-1706.667, 2);
  });
});
