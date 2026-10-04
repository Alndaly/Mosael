/**
 * 截屏:可见区域、整页长图、框选区域 —— 主进程这一半(几何在 pageToolsCore)。
 */
import { nativeImage, type NativeImage, type WebContents } from "electron";

import { sharedViews } from "./accountViews";
import { PageToolError, foreground, pageOf } from "./pageTarget";
import { planFullPage, regionCropRect, type PageInfo, type SelectionFraction } from "./pageToolsCore";

export interface PageCapture {
  /** PNG 字节。 */
  bytes: Uint8Array;
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

/** 可见区域 / 整页长图。 */
export async function capturePage(mode: "visible" | "full"): Promise<PageCapture> {
  const { webContents: wc } = foreground();
  const page = pageOf(wc);
  const capturedAt = new Date().toISOString();
  if (mode === "visible") return asCapture(await wc.capturePage(), page, capturedAt);
  const { png, truncated } = await captureFullPage(wc);
  return asCapture(nativeImage.createFromBuffer(png), page, capturedAt, truncated);
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
