import type { BoardItem } from "@/api/domains/boards";

/** A scene's exported camera frame is an image input, regardless of its canvas node kind. */
export function boardAssetSources(items: BoardItem[]) {
  const seen = new Set<string>();
  return items.flatMap((item) => {
    if (!item.asset_id || seen.has(item.asset_id)) return [];
    const kind = item.kind === "scene" ? "image" : item.kind;
    if (kind !== "image" && kind !== "video" && kind !== "audio") return [];
    seen.add(item.asset_id);
    return [{ assetId: item.asset_id, kind }];
  });
}
