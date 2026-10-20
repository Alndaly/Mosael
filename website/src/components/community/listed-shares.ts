/**
 * 官方列表 + 用户分享的合并规则(纯逻辑,node 测试直接 import)。
 *
 * `/plugins`、`/workflows` 和社区首页 `/community` 的官方条目在构建期就从仓库读好了
 * (`lib/registry`),它们是 **静态卡片**,带着权限数、工具数、安装入口 —— 不搬走、不重做。
 * 这里只负责把云端 `GET /shares?kind=…&locale=…` 返回的分享接在同一张网格的后面:
 *
 * 1. **官方在前**:官方静态条目按 registry 的顺序(按名字)排在最前;
 * 2. **分享在后,新的在前**:用户分享(`slug === null`)和 slug 命中不了静态条目的官方分享
 *    都画成分享卡片,按 `created_at` 从新到旧;
 * 3. **命中静态条目的官方分享不重复**:`slug` 等于某个静态条目的 slug 时跳过 —— 那条内容
 *    的详情页已经在 `/plugins/<slug>` / `/workflows/<slug>`,再画一张分享卡片就是同一件
 *    东西出现两次。
 *
 * **云端不可达不是列表页的错误**:内容优先,拿不到分享就只渲染静态列表。所以取数函数
 * 把失败吞成空数组,页面里没有错误块、也没有"重试"按钮 —— 官方内容不该因为社区服务
 * 挂了而变得不可用。
 */
import type { Locale } from "@/i18n/config";
import {
  cloudLocale,
  type CloudShare,
  type CloudSharePage,
  type CloudShareQuery,
} from "@/lib/cloud";

/** 一次取多少条分享。50 是云端的 `MAX_LIMIT`;列表暂不翻页,超出的等以后再加游标。 */
export const LISTED_SHARE_LIMIT = 50;

/** 列表页要混进来的两种官方内容。 */
export type ListedShareKind = "plugin" | "workflow";

/**
 * 列表取数接受的 kind:上面两种官方内容,外加 **board**。
 *
 * 画布没有官方静态条目(`lib/registry` 里只有插件 / 工作流),所以它不出现在合并规则里;
 * 但 `/boards` 和社区首页的第三组仍要按同一个接口取数 —— 签名放宽到这里,取数 / 语言兜底
 * 与官方组逐字一致。
 */
export type ListedShareListKind = ListedShareKind | "board";

/** 合并后的一项:要么是静态官方条目,要么是一张分享卡片。 */
export type ListingItem<T> =
  | { kind: "official"; official: T }
  | { kind: "share"; share: CloudShare };

/** 从云端拿一份当前语言的分享列表。失败 → 空数组(页面只留静态列表)。 */
export async function fetchListedShares(
  load: (query: CloudShareQuery) => Promise<CloudSharePage>,
  kind: ListedShareListKind,
  locale: Locale,
): Promise<CloudShare[]> {
  const wanted = cloudLocale(locale);
  try {
    const page = await load({ kind, locale: wanted, sort: "new", limit: LISTED_SHARE_LIMIT });
    // 请求已经带了 locale;这里再按响应兜一次底,云端万一回错语言也不会漏到页面上。
    return page.items.filter((share) => share.locale === wanted);
  } catch {
    return [];
  }
}

/** 分享的时间戳(ISO 字符串)。解析不了就排到最后,而不是让排序抛错。 */
function timestamp(share: CloudShare): number {
  const value = Date.parse(share.created_at);
  return Number.isNaN(value) ? 0 : value;
}

/**
 * 分享卡片:跳过 slug 命中静态官方条目的那些,再按新→旧排序。
 *
 * 用户分享的 `slug` 是 `null`(云端从不让用户写这一列),所以它们永远留下;官方分享只要
 * slug 没命中静态条目(例如以后新增、官网还没写详情页的)也留下。
 */
export function listedShares(
  shares: readonly CloudShare[],
  officialSlugs: readonly string[],
): CloudShare[] {
  const official = new Set(officialSlugs);
  return shares
    .filter((share) => !share.slug || !official.has(share.slug))
    .sort((a, b) => timestamp(b) - timestamp(a) || a.id.localeCompare(b.id));
}

/** 同一张网格里的顺序:官方条目全部在前,分享卡片全部在后。 */
export function mergeListing<T>(
  officialItems: readonly T[],
  shares: readonly CloudShare[],
): ListingItem<T>[] {
  return [
    ...officialItems.map((official) => ({ kind: "official" as const, official })),
    ...shares.map((share) => ({ kind: "share" as const, share })),
  ];
}
