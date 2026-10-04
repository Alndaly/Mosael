/**
 * 截屏:可见区域、整页长图、某个元素、框选区域 —— 主进程这一半(几何在 pageToolsCore)。
 *
 * **只有这一份实现。** 顶栏的「截屏」截前台那一页,工作流的「截图」节点截自动化会话的那一页(见
 * actionCapture),都走 captureContents;区别只在截哪个页面、截完交给谁。
 */
import { nativeImage, type NativeImage, type WebContents } from "electron";

import { sharedViews } from "./accountViews";
import { PageToolError, foreground, pageOf } from "./pageTarget";
import {
  planClip,
  planFullPage,
  regionCropRect,
  screenRatio,
  type PageInfo,
  type PageRect,
  type SelectionFraction,
} from "./pageToolsCore";

export interface PageCapture {
  /** PNG 字节(自己的一份拷贝,能直接装进 Blob)。 */
  bytes: Uint8Array<ArrayBuffer>;
  width: number;
  height: number;
  /** 整页长图比上限长,只截了前面一段。 */
  truncated: boolean;
  page: PageInfo;
  /** 截取那一刻(ISO 8601)。 */
  capturedAt: string;
}

function asCapture(image: NativeImage, page: PageInfo, capturedAt: string, truncated = false): PageCapture {
  if (image.isEmpty()) throw new PageToolError("capture_failed");
  const { width, height } = image.getSize();
  return { bytes: new Uint8Array(image.toPNG()), width, height, truncated, page, capturedAt };
}

/** 顶栏:前台那一页的可见区域 / 整页长图。 */
export function capturePage(mode: "visible" | "full"): Promise<PageCapture> {
  return captureContents(foreground().webContents, mode);
}

/** 截不到那个元素:页面上没有它,或者它没有大小(被藏起来了)。 */
export class ElementCaptureError extends Error {
  constructor(readonly reason: "missing" | "empty") {
    super(`page-capture: element ${reason}`);
    this.name = "ElementCaptureError";
  }
}

/**
 * 截一个页面:可见区域、整页长图、某个元素(`selector`,截它整块,哪怕有一部分在视口外)。
 *
 * 缩小显示的页面(悬浮面板里的自动化会话缩到三成上下)截图那一下按原清晰度渲染(见 atNativeResolution),
 * 截出来和前台页面一样清楚、边界一样准。
 */
export async function captureContents(
  wc: WebContents,
  mode: "visible" | "full" | "element",
  opts: { selector?: string } = {},
): Promise<PageCapture> {
  const page = pageOf(wc);
  const capturedAt = new Date().toISOString();
  const zoom = wc.getZoomFactor();
  const shoot = () => shootAs(wc, mode, opts.selector ?? "", page, capturedAt);
  return Math.abs(zoom - 1) < 1e-3 ? shoot() : atNativeResolution(wc, zoom, shoot);
}

async function shootAs(
  wc: WebContents,
  mode: "visible" | "full" | "element",
  selector: string,
  page: PageInfo,
  capturedAt: string,
): Promise<PageCapture> {
  if (mode === "visible") return asCapture(await wc.capturePage(), page, capturedAt);
  if (mode === "full") {
    const { png, truncated } = await captureFullPage(wc);
    return asCapture(nativeImage.createFromBuffer(png), page, capturedAt, truncated);
  }
  const rect = await elementRect(wc, selector);
  const ratio = Number(await wc.executeJavaScript("window.devicePixelRatio")) || 1;
  const plan = planClip(rect, ratio);
  if (!plan) throw new ElementCaptureError("empty");
  const shot = nativeImage.createFromBuffer(await cdpShot(wc, plan.clip));
  // 按设备像素裁到元素自己(见 planClip);Chromium 出图比预计的少一两像素时夹进图里。
  const size = shot.getSize();
  const x = Math.min(plan.crop.x, Math.max(0, size.width - 1));
  const y = Math.min(plan.crop.y, Math.max(0, size.height - 1));
  const image = shot.crop({ x, y, width: Math.min(plan.crop.width, size.width - x), height: Math.min(plan.crop.height, size.height - y) });
  return asCapture(image, page, capturedAt, plan.truncated);
}

/**
 * 缩小显示的页面按原清晰度截:截图那一下把缩放换回 1,用设备模拟让页面按**同样的 CSS 视口**、屏幕的设备
 * 像素比渲染,再按原来的缩放比例缩回视图那么大显示(`scale`)—— 页面不重排、不滚动,面板里看到的还是那一页;
 * 截完撤掉模拟、缩放还原(截失败了也还原)。
 *
 * 为什么不直接让 CDP 放大截:缩到 0.3 的页面是按 0.6 的设备像素比画的,CDP 的 scale 只是把这张小图放大 ——
 * 实测 1px 的边框糊成灰的、外圈的红色渗进边上、出图尺寸也差好几个像素。
 */
async function atNativeResolution<T>(wc: WebContents, zoom: number, shoot: () => Promise<T>): Promise<T> {
  const view = (await wc.executeJavaScript("({ width: innerWidth, height: innerHeight, ratio: devicePixelRatio })")) as {
    width: number;
    height: number;
    ratio: number;
  };
  try {
    if (!wc.debugger.isAttached()) wc.debugger.attach("1.3");
  } catch {
    throw new PageToolError("capture_failed"); // 开着 DevTools 时 attach 会被拒
  }
  const screen = screenRatio(view.ratio / zoom);
  wc.setZoomFactor(1);
  try {
    await wc.debugger.sendCommand("Emulation.setDeviceMetricsOverride", {
      width: view.width,
      height: view.height,
      deviceScaleFactor: screen,
      mobile: false,
      scale: zoom,
    });
    // 缩放和设备模拟都是异步送到页面的:等页面读到的设备像素比真变成屏幕的,再等它按新的画完一帧。
    // 不等的话元素位置还是按缩小时的排版读的(实跑:37.734 而不是 37.75),裁出来顶边、左边带进一行外圈。
    await untilRatio(wc, screen);
    await wc.executeJavaScript("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))");
    return await shoot();
  } finally {
    await wc.debugger.sendCommand("Emulation.clearDeviceMetricsOverride").catch(() => undefined);
    wc.setZoomFactor(zoom);
  }
}

/** 等页面读到的设备像素比变成 `target`(最多等一秒;等不到就照样截,不卡住这一步)。 */
async function untilRatio(wc: WebContents, target: number): Promise<void> {
  const deadline = Date.now() + 1_000;
  while (Date.now() < deadline) {
    const ratio = Number(await wc.executeJavaScript("devicePixelRatio"));
    if (Math.abs(ratio - target) < 0.01) return;
    await new Promise((resolve) => setTimeout(resolve, 16));
  }
}

/** 元素在文档里的位置(CSS 像素);页面上没有它就抛 missing。 */
async function elementRect(wc: WebContents, selector: string): Promise<PageRect> {
  const rect = (await wc.executeJavaScript(
    `(() => {
      let el = null;
      try { el = document.querySelector(${JSON.stringify(selector)}); } catch { return null; }
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
    })()`,
  )) as PageRect | null;
  if (!rect) throw new ElementCaptureError("missing");
  return rect;
}

/**
 * CDP 截一块。`captureBeyondViewport`:元素有一部分在视口外也整块截;视图不在屏幕上(挂在窗口外面)时
 * 也只有这样 Chromium 才肯出一帧(实测不带它的截图一直等不到)。debugger 的挂法同整页长图。
 */
async function cdpShot(wc: WebContents, clip: PageRect & { scale: number }): Promise<Buffer> {
  try {
    if (!wc.debugger.isAttached()) wc.debugger.attach("1.3");
    const shot = (await wc.debugger.sendCommand("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      fromSurface: true,
      clip,
    })) as { data: string };
    return Buffer.from(shot.data, "base64");
  } catch {
    throw new PageToolError("capture_failed");
  }
}

/**
 * 整页长图:CDP 的 `captureBeyondViewport` 让 Chromium 把整页一次画进一张图,不用滚动拼接 ——
 * 拼接会把吸顶的导航条在每一截里重复一遍,懒加载的内容也会在滚动途中跳动错位。
 *
 * 局限要说清:**还没进入过视口的懒加载图片可能是空的**(页面只在滚到时才去取);超过
 * MAX_FULL_PAGE_HEIGHT 的部分不截(见 planFullPage)。
 *
 * debugger 可能已被 PageDriver 挂上(发布 / RPA 驱动同一个视图时),那时直接复用、不再 attach;
 * 我们挂上的也不摘 —— 摘的那一刻若驱动正在用它,它的下一条命令就会失败。
 */
async function captureFullPage(wc: WebContents): Promise<{ png: Buffer; truncated: boolean }> {
  try {
    if (!wc.debugger.isAttached()) wc.debugger.attach("1.3");
    const metrics = (await wc.debugger.sendCommand("Page.getLayoutMetrics")) as {
      cssContentSize?: { width: number; height: number };
      contentSize: { width: number; height: number };
      cssLayoutViewport?: { clientWidth: number; clientHeight: number };
      layoutViewport: { clientWidth: number; clientHeight: number };
    };
    const content = metrics.cssContentSize ?? metrics.contentSize;
    const layout = metrics.cssLayoutViewport ?? metrics.layoutViewport;
    const ratio = Number(await wc.executeJavaScript("window.devicePixelRatio")) || 1;
    const plan = planFullPage(content, { width: layout.clientWidth, height: layout.clientHeight }, ratio);
    const shot = (await wc.debugger.sendCommand("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      fromSurface: true,
      clip: { x: 0, y: 0, width: plan.width, height: plan.height, scale: plan.scale },
    })) as { data: string };
    return { png: Buffer.from(shot.data, "base64"), truncated: plan.truncated };
  } catch (error) {
    if (error instanceof PageToolError) throw error;
    // 开着 DevTools 时 attach 会被拒;页面在截图途中跳走也会让命令失败。
    throw new PageToolError("full_page_unavailable");
  }
}

/** 框选进行中:冻结的那一帧和它的出处,等渲染层交回框。 */
let pendingRegion: { viewId: string; image: NativeImage; page: PageInfo; capturedAt: string } | null = null;

/**
 * 框选第一步:冻结当前画面、藏起原生视图,把画面交给渲染层 —— 原生视图上画不了框,渲染层在
 * 原处铺这张图让人拖。页面本身不受影响(只藏不摘,不重排)。
 */
export async function beginRegionCapture(): Promise<{ frame: string; width: number; height: number }> {
  const target = foreground();
  const image = await target.webContents.capturePage();
  if (image.isEmpty()) throw new PageToolError("capture_failed");
  pendingRegion = { viewId: target.id, image, page: pageOf(target.webContents), capturedAt: new Date().toISOString() };
  sharedViews()?.setForegroundHidden("region", true);
  const { width, height } = image.getSize();
  return { frame: image.toDataURL(), width, height };
}

/** 框选第二步:按框裁出那一块(没框 / 框太小 / 取消 → null),视图亮回来。 */
export function finishRegionCapture(selection: SelectionFraction | null): PageCapture | null {
  const pending = pendingRegion;
  pendingRegion = null;
  sharedViews()?.setForegroundHidden("region", false);
  if (!pending || !selection) return null;
  const size = pending.image.getSize();
  const rect = regionCropRect(selection, size);
  if (!rect) return null;
  return asCapture(pending.image.crop(rect), pending.page, pending.capturedAt);
}
