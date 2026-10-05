import { assetFileUrl, assetPreviewUrl, type BoardItem } from "@/api/client";
import type { ImagePreviewItem } from "@/components/app/image-preview";

/** 两格的上沿差在这个比例(按矮的那格的高)以内,就算同一行。 */
const SAME_ROW = 0.5;
/** 没量过高度的格子(刚放上去)按这个高度算。 */
const FALLBACK_HEIGHT = 160;

/**
 * 选中的几格里能看大图的那些 —— 图片格、视频格(已经有素材的),**按画板上读的顺序**:一行一行从上往下,
 * 行里从左往右。灯箱里左右翻就是这个先后。
 *
 * 不按选中的先后,也不按节点数组的先后(那是叠放次序,和眼睛看到的位置无关)。「同一行」要容差:
 * 手摆的一排图上沿总差几个像素,只按 y 排的话,那一排会按谁略高一点乱跳。
 */
export function boardPreviewGallery(items: readonly BoardItem[]): ImagePreviewItem[] {
  const visual = items
    .filter((item) => (item.kind === "image" || item.kind === "video") && item.asset_id)
    .sort((a, b) => a.y - b.y || a.x - b.x);
  const rows: BoardItem[][] = [];
  for (const item of visual) {
    const row = rows.at(-1);
    const head = row?.[0];
    const tolerance = head ? Math.min(head.height ?? FALLBACK_HEIGHT, item.height ?? FALLBACK_HEIGHT) * SAME_ROW : 0;
    if (row && head && item.y - head.y <= tolerance) row.push(item);
    else rows.push([item]);
  }
  return rows.flatMap((row) =>
    [...row].sort((a, b) => a.x - b.x).map((item) => {
      const id = item.asset_id as string;
      const title = item.title || item.text || "";
      return item.kind === "video" ? { src: assetFileUrl(id), title, video: true } : { src: assetPreviewUrl(id), title };
    }),
  );
}
