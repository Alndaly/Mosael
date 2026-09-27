import type { BoardItem } from "@/api/domains/boards";

/**
 * 这几格(连到某一格上的上游)能给出的素材。3D 场景格不在其中:它给的是场景,生成时现渲成参考(ADR 0029)。
 *
 * `itemId` 是给出它的那一格 —— 面板照它挂进槽位时记成 `from`,线断了由服务端摘掉。
 */
export function boardAssetSources(items: BoardItem[]) {
  const seen = new Set<string>();
  return items.flatMap((item) => {
    if (!item.asset_id || seen.has(item.asset_id)) return [];
    const kind = item.kind;
    if (kind !== "image" && kind !== "video" && kind !== "audio") return [];
    seen.add(item.asset_id);
    return [{ assetId: item.asset_id, kind, itemId: item.id }];
  });
}
