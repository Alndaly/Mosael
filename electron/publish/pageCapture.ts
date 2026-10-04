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
  cdpClip,
  planClip,
  planFullPage,
  regionCropRect,
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
 * 页面被缩放过(悬浮面板里的自动化会话缩到三成上下)时照样按屏幕原生清晰度出图(见 pageToolsCore.clipScale)
 * —— 直接 capturePage 截出来的只有面板那么大一点。
 */
export async function captureContents(
  wc: WebContents,
  mode: "visible" | "full" | "element",
  opts: { selector?: string } = {},
): Promise<PageCapture> {
  const page = pageOf(wc);
  const capturedAt = new Date().toISOString();
  const zoom = wc.getZoomFactor();
  if (mode === "visible" && Math.abs(zoom - 1) < 1e-3) return asCapture(await wc.capturePage(), page, capturedAt);
  if (mode === "full") {
    const { png, truncated } = await captureFullPage(wc, zoom);
    return asCapture(nativeImage.createFromBuffer(png), page, capturedAt, truncated);
  }
  const rect = mode === "element" ? await elementRect(wc, opts.selector ?? "") : await visibleRect(wc);
  const ratio = Number(await wc.executeJavaScript("window.devicePixelRatio")) || 1;
  const plan = planClip(rect, ratio, zoom);
  if (!plan) throw new ElementCaptureError("empty");
  const png = await cdpShot(wc, plan.clip, mode === "element");
  return asCapture(nativeImage.createFromBuffer(png), page, capturedAt, plan.truncated);
}

/** 可见区域在文档里的位置(CSS 像素)。 */
function visibleRect(wc: WebContents): Promise<PageRect> {
  return wc.executeJavaScript(
    "({ x: window.scrollX, y: window.scrollY, width: document.documentElement.clientWidth || window.innerWidth, height: document.documentElement.clientHeight || window.innerHeight })",
  ) as Promise<PageRect>;
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

/** CDP 截一块。debugger 的挂法同整页长图(见 captureFullPage 的说明)。 */
async function cdpShot(wc: WebContents, clip: PageRect & { scale: number }, beyondViewport: boolean): Promise<Buffer> {
  try {
    if (!wc.debugger.isAttached()) wc.debugger.attach("1.3");
    const shot = (await wc.debugger.sendCommand("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: beyondViewport,
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
async function captureFullPage(wc: WebContents, zoom: number): Promise<{ png: Buffer; truncated: boolean }> {
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
    const plan = planFullPage(content, { width: layout.clientWidth, height: layout.clientHeight }, ratio, zoom);
    const shot = (await wc.debugger.sendCommand("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      fromSurface: true,
      clip: cdpClip({ x: 0, y: 0, width: plan.width, height: plan.height }, plan.scale, zoom),
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
  sharedViews()?.setForegroundHidden(true);
  const { width, height } = image.getSize();
  return { frame: image.toDataURL(), width, height };
}

/** 框选第二步:按框裁出那一块(没框 / 框太小 / 取消 → null),视图亮回来。 */
export function finishRegionCapture(selection: SelectionFraction | null): PageCapture | null {
  const pending = pendingRegion;
  pendingRegion = null;
  sharedViews()?.setForegroundHidden(false);
  if (!pending || !selection) return null;
  const size = pending.image.getSize();
  const rect = regionCropRect(selection, size);
  if (!rect) return null;
  return asCapture(pending.image.crop(rect), pending.page, pending.capturedAt);
}
