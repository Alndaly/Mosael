/**
 * 采集页面图片 —— 主进程这一半:列出页面上的图、用这个档案的会话把字节取回来(筛选与认格式在 pageImagesCore)。
 */
import { fetchBytes } from "./pageFetch";
import { foreground, pageOf } from "./pageTarget";
import { IMAGE_SCAN_SCRIPT, pickPageImages, sniffImage, type PageImage } from "./pageImagesCore";
import type { PageInfo } from "./pageToolsCore";

/** 单张图片最多多大。和后端收素材的上限一致(见 domain/assets/web_capture.MAX_CAPTURE_BYTES)。 */
export const MAX_IMAGE_BYTES = 40 * 1024 * 1024;
/** 同时取几张。 */
const IMAGE_CONCURRENCY = 6;

/**
 * 最近一次列图的结果。取图只认这份清单里的地址 —— 渲染层不能借这条通道,拿着档案的登录态
 * 去取任意地址。
 */
let listedImages: { viewId: string; page: PageInfo; urls: Set<string> } | null = null;

export async function listImages(): Promise<{ page: PageInfo; images: PageImage[] }> {
  const target = foreground();
  const page = pageOf(target.webContents);
  const raw = (await target.webContents.mainFrame.executeJavaScript(IMAGE_SCAN_SCRIPT).catch(() => [])) as PageImage[];
  const images = pickPageImages(Array.isArray(raw) ? raw : []);
  listedImages = { viewId: target.id, page, urls: new Set(images.map((image) => image.url)) };
  return { page, images };
}

export type FetchedImage =
  | { url: string; ok: true; bytes: Uint8Array; mime: string }
  | { url: string; ok: false; reason: "failed" | "too_large" | "not_image" | "not_listed" };

/** 取这些图的字节(缩略图和入库都用它,只取一次)。文件头不是图片的不收。 */
export async function fetchImages(urls: string[]): Promise<FetchedImage[]> {
  const target = foreground();
  const listed = listedImages && listedImages.viewId === target.id ? listedImages : null;
  const results: FetchedImage[] = new Array(urls.length);
  let next = 0;
  const worker = async () => {
    while (next < urls.length) {
      const index = next;
      next += 1;
      const url = urls[index];
      if (!listed?.urls.has(url)) {
        results[index] = { url, ok: false, reason: "not_listed" };
        continue;
      }
      const fetched = await fetchBytes(target.webContents, url, listed.page.url, MAX_IMAGE_BYTES);
      if (!fetched.ok) {
        results[index] = { url, ok: false, reason: fetched.reason };
        continue;
      }
      const mime = sniffImage(fetched.bytes);
      results[index] = mime ? { url, ok: true, bytes: fetched.bytes, mime } : { url, ok: false, reason: "not_image" };
    }
  };
  await Promise.all(Array.from({ length: Math.min(IMAGE_CONCURRENCY, urls.length) }, worker));
  return results;
}
