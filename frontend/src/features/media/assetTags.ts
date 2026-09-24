import type { Asset } from "@/api/client";

/** 勾了几个标签时怎么算:同时带有(越勾越窄)/ 带有任一(越勾越宽)。 */
export type TagMatch = "all" | "any";

export const TAG_MATCHES = ["all", "any"] as const satisfies readonly TagMatch[];

/** OpenAPI 里 tags 带默认值所以是可选字段;统一成数组再用。 */
export const assetTags = (asset: Asset): string[] => asset.tags ?? [];

/**
 * 每个标签挂在几条素材上,按标签名排好序。
 *
 * 筛选弹层靠它列标签、给每个标签标数量;键的顺序就是列出来的顺序。素材库和剪辑页的素材面板
 * 都从这里取 —— 两处的标签列表、排序、数量才会是同一个答案。
 */
export function tagCounts(assets: readonly Asset[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const asset of assets) for (const tag of assetTags(asset)) if (tag) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  return new Map([...counts].sort(([a], [b]) => a.localeCompare(b, "zh-CN")));
}

/** 这条素材过不过标签筛选。一个都没勾就是不筛。 */
export function matchesTags(asset: Asset, chosen: readonly string[], match: TagMatch): boolean {
  if (chosen.length === 0) return true;
  const tags = assetTags(asset);
  return match === "all" ? chosen.every((tag) => tags.includes(tag)) : chosen.some((tag) => tags.includes(tag));
}
