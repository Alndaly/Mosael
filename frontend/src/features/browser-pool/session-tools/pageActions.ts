/**
 * 顶栏页面工具里**不碰界面**的那一半(截屏这一份;视频、图片各在 videoActions / imageActions)。
 *
 * 主进程交来字节和页面信息(window.mosaelPageTools,只作用于前台视图),这里决定怎么交给后端:截图带着出处
 * 走 `/api/assets/capture`。框选的几何也在这里 —— 界面只交比例,原图多少像素只有主进程知道。
 */
import { importWebCapture, type Asset, type WebCaptureKind } from "@/api/client";

export type PageToolsBridge = NonNullable<Window["mosaelPageTools"]>;
export type PageCapture = Awaited<ReturnType<PageToolsBridge["capture"]>>;
export type PageInfo = PageCapture["page"];

/** 主进程拒绝时消息里带的原因码(见 electron/publish/pageTarget.ts 的 PageToolError)。 */
export type PageToolErrorCode = "no_page" | "capture_failed" | "full_page_unavailable";

export function pageToolErrorCode(error: unknown): PageToolErrorCode | null {
  const match = /page-tools: (no_page|capture_failed|full_page_unavailable)/.exec(String((error as Error)?.message ?? error));
  return match ? (match[1] as PageToolErrorCode) : null;
}

export type ShotMode = "visible" | "full" | "region";

export const SHOT_KIND: Record<ShotMode, WebCaptureKind> = {
  visible: "screenshot_visible",
  full: "screenshot_full",
  region: "screenshot_region",
};

/** 一张截图带着出处入库。 */
export function saveScreenshot(workspaceId: string, capture: PageCapture, mode: ShotMode, name: string): Promise<Asset> {
  return importWebCapture({
    workspaceId,
    file: new Blob([capture.bytes as Uint8Array<ArrayBuffer>], { type: "image/png" }),
    capture: SHOT_KIND[mode],
    pageUrl: capture.page.url,
    pageTitle: capture.page.title,
    capturedAt: capture.capturedAt,
    name,
  });
}

/** 素材名:页面标题(没有就用域名)· 截图的种类。 */
export function captureName(page: PageInfo, suffix: string): string {
  let host = page.url;
  try {
    host = new URL(page.url).hostname;
  } catch {
    /* 地址不像样就原样用 */
  }
  return `${(page.title || host).slice(0, 160)} · ${suffix}`;
}

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * 框选:冻结画面上从 `from` 拖到 `to`(都是窗口坐标),换成画面上的比例(0–1)。拖出画面的部分夹回来;
 * 比例与画面在界面上显示多大无关 —— 原图多少像素只有主进程知道,换算在那一侧做。
 */
export function selectionFraction(from: Point, to: Point, box: Box): { x: number; y: number; width: number; height: number } {
  const clampX = (value: number) => Math.min(1, Math.max(0, (value - box.left) / box.width));
  const clampY = (value: number) => Math.min(1, Math.max(0, (value - box.top) / box.height));
  const x1 = clampX(from.x);
  const x2 = clampX(to.x);
  const y1 = clampY(from.y);
  const y2 = clampY(to.y);
  return { x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) };
}

/** 冻结画面在界面上显示多大:整张放进可用区域(不放大),左上角对齐网页原来的位置。 */
export function frameDisplaySize(frame: { width: number; height: number }, area: { width: number; height: number }) {
  const scale = Math.min(area.width / frame.width, area.height / frame.height);
  return { width: Math.round(frame.width * scale), height: Math.round(frame.height * scale) };
}
