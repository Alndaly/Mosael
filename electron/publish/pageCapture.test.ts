/**
 * 截图交给 Chromium 的那几步:缩小显示的页面(悬浮面板里缩到 0.3 左右)截图那一下按原清晰度渲染,截完原样
 * 复原;元素截图按设备像素裁到元素自己的边界,不多带一行外圈。
 *
 * 页面和 CDP 换成记账的假货:CDP 截出来的「图」就是一张按请求算出尺寸的假图,裁切照记下来的矩形缩小。
 * 真页面上逐像素验四条边在隔离实跑里做(见提交说明)。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

/** 假图:只记尺寸,裁切按矩形缩小(越界就算失败,真 nativeImage 越界会给空图)。 */
class FakeImage {
  constructor(
    readonly width: number,
    readonly height: number,
    readonly cropped: { x: number; y: number; width: number; height: number } | null = null,
  ) {}
  isEmpty() {
    return this.width <= 0 || this.height <= 0;
  }
  getSize() {
    return { width: this.width, height: this.height };
  }
  crop(rect: { x: number; y: number; width: number; height: number }) {
    if (rect.x < 0 || rect.y < 0 || rect.x + rect.width > this.width || rect.y + rect.height > this.height) {
      return new FakeImage(0, 0, rect);
    }
    return new FakeImage(rect.width, rect.height, rect);
  }
  toPNG() {
    return Buffer.from(JSON.stringify({ w: this.width, h: this.height }));
  }
}

vi.mock("electron", () => ({
  nativeImage: {
    createFromBuffer: (buffer: Buffer) => {
      const { w, h } = JSON.parse(buffer.toString("utf8")) as { w: number; h: number };
      return new FakeImage(w, h);
    },
  },
}));
vi.mock("./accountViews", () => ({ sharedViews: () => null }));

const { captureContents } = await import("./pageCapture");

/** 一个假页面:CSS 视口 1280×800,屏幕 2 倍;缩放 `zoom`;元素在小数坐标上。 */
function fakePage(zoom: number) {
  const log: Array<[string, unknown]> = [];
  let currentZoom = zoom;
  let overridden: { deviceScaleFactor: number } | null = null;
  const wc = {
    getURL: () => "https://example.com/post",
    getTitle: () => "一篇帖子",
    getZoomFactor: () => currentZoom,
    setZoomFactor: (next: number) => {
      log.push(["zoom", next]);
      currentZoom = next;
    },
    capturePage: async () => new FakeImage(1280 * 2, 800 * 2),
    executeJavaScript: async (code: string) => {
      if (code.includes("devicePixelRatio") && !code.includes("innerWidth")) return overridden ? overridden.deviceScaleFactor : 2 * currentZoom;
      if (code.includes("innerWidth") && code.includes("innerHeight") && !code.includes("scrollX")) {
        return { width: 1280, height: 800, ratio: overridden ? overridden.deviceScaleFactor : 2 * currentZoom };
      }
      if (code.includes("querySelector")) return { x: 37.75, y: 613.25, width: 200.5, height: 80.25 };
      if (code.includes("scrollX")) return { x: 0, y: 0, width: 1280, height: 800 };
      if (code.includes("requestAnimationFrame")) return true;
      return null;
    },
    debugger: {
      attached: false,
      isAttached() {
        return this.attached;
      },
      attach() {
        this.attached = true;
      },
      async sendCommand(method: string, params?: Record<string, unknown>) {
        log.push([method, params]);
        if (method === "Emulation.setDeviceMetricsOverride") overridden = params as { deviceScaleFactor: number };
        if (method === "Emulation.clearDeviceMetricsOverride") overridden = null;
        if (method === "Page.captureScreenshot") {
          const clip = params!.clip as { width: number; height: number; scale: number };
          // Chromium 把小数宽高截成整数 CSS 像素再乘比例(实测),出图 = 整数宽高 × scale × 渲染时的设备像素比。
          const dpr = overridden ? overridden.deviceScaleFactor : 2 * currentZoom;
          const w = Math.floor(clip.width) * clip.scale * dpr;
          const h = Math.floor(clip.height) * clip.scale * dpr;
          return { data: Buffer.from(JSON.stringify({ w: Math.round(w), h: Math.round(h) })).toString("base64") };
        }
        return {};
      },
    },
  };
  return { wc, log, zoom: () => currentZoom };
}

const parse = (bytes: Uint8Array) => JSON.parse(Buffer.from(bytes).toString("utf8")) as { w: number; h: number };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("截图交给 Chromium 的那几步", () => {
  it("元素截图按设备像素裁到元素自己的边界:401×160,不多一行外圈", async () => {
    const { wc } = fakePage(1);
    const shot = await captureContents(wc as never, "element", { selector: "#el" });
    expect(parse(shot.bytes)).toEqual({ w: 401, h: 160 });
    expect([shot.width, shot.height]).toEqual([401, 160]);
  });

  it("缩到 0.3 的页面:截图那一下按同样的 CSS 视口、屏幕的设备像素比渲染(显示缩回面板那么大),截完原样复原", async () => {
    const { wc, log, zoom } = fakePage(0.3);
    const shot = await captureContents(wc as never, "element", { selector: "#el" });
    expect([shot.width, shot.height]).toEqual([401, 160]);
    const methods = log.map(([name]) => name);
    const override = log.find(([name]) => name === "Emulation.setDeviceMetricsOverride")![1];
    expect(override).toEqual({ width: 1280, height: 800, deviceScaleFactor: 2, mobile: false, scale: 0.3 });
    // 先换到原清晰度、再截、再复原。
    expect(methods.indexOf("Emulation.setDeviceMetricsOverride")).toBeLessThan(methods.indexOf("Page.captureScreenshot"));
    expect(methods.indexOf("Page.captureScreenshot")).toBeLessThan(methods.indexOf("Emulation.clearDeviceMetricsOverride"));
    expect(log.filter(([name]) => name === "zoom").map(([, value]) => value)).toEqual([1, 0.3]);
    expect(zoom()).toBe(0.3);
  });

  it("缩到 0.3 的页面:等页面真按屏幕的设备像素比排好了才读元素位置(缩放是异步送到页面的)", async () => {
    const { wc, log } = fakePage(0.3);
    // 页面晚两拍才收到缩放和设备模拟:这两拍里读到的还是缩小时的设备像素比和排版。
    let lagging = 2;
    const read = wc.executeJavaScript;
    wc.executeJavaScript = async (code: string) => {
      if (code.trim() === "devicePixelRatio" && lagging > 0) {
        lagging -= 1;
        log.push(["stale-ratio", 0.6]);
        return 0.6;
      }
      if (code.includes("querySelector") && lagging > 0) return { x: 37.734375, y: 613.2291259765625, width: 200.49478149414062, height: 80.234375 };
      return read(code);
    };
    const shot = await captureContents(wc as never, "element", { selector: "#el" });
    expect([shot.width, shot.height]).toEqual([401, 160]);
    expect(log.filter(([name]) => name === "stale-ratio")).toHaveLength(2);
  });

  it("缩到 0.3 的页面截图失败了也复原(缩放、设备模拟都撤回)", async () => {
    const { wc, log, zoom } = fakePage(0.3);
    const send = wc.debugger.sendCommand.bind(wc.debugger);
    wc.debugger.sendCommand = async (method: string, params?: Record<string, unknown>) => {
      if (method === "Page.captureScreenshot") throw new Error("boom");
      return send(method, params);
    };
    await expect(captureContents(wc as never, "element", { selector: "#el" })).rejects.toThrow();
    expect(log.map(([name]) => name)).toContain("Emulation.clearDeviceMetricsOverride");
    expect(zoom()).toBe(0.3);
  });

  it("没缩放的页面不碰设备模拟", async () => {
    const { wc, log } = fakePage(1);
    await captureContents(wc as never, "element", { selector: "#el" });
    expect(log.map(([name]) => name)).not.toContain("Emulation.setDeviceMetricsOverride");
    expect(log.filter(([name]) => name === "zoom")).toEqual([]);
  });
});
