import type { BoardItem } from "@/api/domains/boards";

/**
 * 这几格(连到某一格上的上游)能给出的素材。A scene's exported camera frame is an image input,
 * regardless of its canvas node kind.
 *
 * `itemId` 是给出它的那一格 —— 面板照它挂进槽位时记成 `from`,线断了由服务端摘掉。
 */
export function boardAssetSources(items: BoardItem[]) {
  const seen = new Set<string>();
  return items.flatMap((item) => {
    if (!item.asset_id || seen.has(item.asset_id)) return [];
    const kind = item.kind === "scene" ? "image" : item.kind;
    if (kind !== "image" && kind !== "video" && kind !== "audio") return [];
    seen.add(item.asset_id);
    return [{ assetId: item.asset_id, kind, itemId: item.id }];
  });
}
