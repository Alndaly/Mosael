/** 带标签的东西:素材、资产都是。标签筛选只认这一个字段,两处共用同一套计数和匹配。 */
type Tagged = { tags?: string[] | null };

/** 勾了几个标签时怎么算:同时带有(越勾越窄)/ 带有任一(越勾越宽)。 */
export type TagMatch = "all" | "any";

export const TAG_MATCHES = ["all", "any"] as const satisfies readonly TagMatch[];

/** OpenAPI 里 tags 带默认值所以是可选字段;统一成数组再用。 */
export const tagsOf = (item: Tagged): string[] => item.tags ?? [];

/**
 * 每个标签挂在几条素材上,按标签名排好序。
 *
 * 筛选弹层靠它列标签、给每个标签标数量;键的顺序就是列出来的顺序。素材库和剪辑页的素材面板
 * 都从这里取,资产库也是 —— 几处的标签列表、排序、数量才会是同一个答案。
 */
export function tagCounts(assets: readonly Tagged[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const asset of assets) for (const tag of tagsOf(asset)) if (tag) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  return sortedTagCounts(counts);
}

/** 服务端数好的标签计数(素材库分页之后,标签候选由 `/api/assets/facets` 给)排成和 `tagCounts` 一样的顺序。 */
export function sortedTagCounts(counts: Iterable<[string, number]> | Record<string, number>): Map<string, number> {
  const entries = Symbol.iterator in counts ? [...(counts as Iterable<[string, number]>)] : Object.entries(counts);
  return new Map(entries.filter(([tag]) => tag).sort(([a], [b]) => a.localeCompare(b, "zh-CN")));
}

/** 这条素材过不过标签筛选。一个都没勾就是不筛。 */
export function matchesTags(asset: Tagged, chosen: readonly string[], match: TagMatch): boolean {
  if (chosen.length === 0) return true;
  const tags = tagsOf(asset);
  return match === "all" ? chosen.every((tag) => tags.includes(tag)) : chosen.some((tag) => tags.includes(tag));
}
