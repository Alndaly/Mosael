/**
 * 采集页面图片:素材名怎么起、带着什么出处入库(主进程那一半在 electron/publish/pageImages)。
 */
import { importWebCapture, type Asset } from "@/api/client";

import type { PageInfo } from "./pageActions";

/** 页面图片的素材名:有 alt 用 alt,没有就用地址的最后一段。 */
export function imageName(url: string, alt: string): string {
  const text = alt.trim();
  if (text) return text.slice(0, 160);
  try {
    const last = decodeURIComponent(new URL(url).pathname.split("/").filter(Boolean).at(-1) ?? "");
    return last.slice(0, 160) || new URL(url).hostname;
  } catch {
    return url.slice(0, 160);
  }
}

/** 一张页面图片带着出处(页面 + 图片自己的地址)入库。 */
export function savePageImage(
  workspaceId: string,
  image: { url: string; alt: string; bytes: Uint8Array; mime: string },
  page: PageInfo,
  capturedAt: string,
): Promise<Asset> {
  return importWebCapture({
    workspaceId,
    file: new Blob([image.bytes as Uint8Array<ArrayBuffer>], { type: image.mime }),
    capture: "page_image",
    pageUrl: page.url,
    pageTitle: page.title,
    capturedAt,
    name: imageName(image.url, image.alt),
    sourceUrl: image.url,
  });
}
