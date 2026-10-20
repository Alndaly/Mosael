import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 社区页头的 tab 列表 —— 只由 (locale, counts) 决定。
 *
 * **这个函数故意不收 `active`。** 旧实现把「分享」写成
 * `...(active === "shares" ? [分享] : [])`:切到 `/plugins` 或 `/workflows` 时,「分享」
 * 这一项整个从页头消失,用户看到的就是「分享列表没了」—— 数据一直在云端,消失的只是入口。
 * 把当前页面挡在函数签名之外,这类「按页面裁剪导航」的写法就从结构上不可能再出现;
 * 当前高亮由页头自己拿 `active` 比对 `tab.id` 完成(见 community-header.tsx)。
 */
export const COMMUNITY_SECTIONS = ["shares", "plugins", "workflows"] as const;

export type CommunitySection = (typeof COMMUNITY_SECTIONS)[number];

/** 页头 tab 上的数字。分享的总数常常拿不到 —— 拿不到就别传,别编一个 0 出来。 */
export type CommunityCounts = {
  /** 已知的分享总数。单页取完、且没在筛选时才是真的总数(见 knownShareCount)。 */
  shares?: number;
  plugins: number;
  workflows: number;
};

export type CommunityTab = { id: CommunitySection; label: string; href: string; count?: number };

const PATHS: Record<CommunitySection, string> = {
  shares: "/community",
  plugins: "/plugins",
  workflows: "/workflows",
};

/**
 * 「分享」的计数只在**拿得到**时上 tab:0 和「不知道」都不显示数字。
 *
 * 0 条分享时显示 `分享 0` 既难看又容易被当成数据出错;不知道总数时更不能拿首屏条数充数。
 */
function shareCount(value: number | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

export function communityTabs(locale: Locale, counts: CommunityCounts): CommunityTab[] {
  const t = getMessages(locale);
  const labels: Record<CommunitySection, string> = {
    shares: t.community.shares,
    plugins: t.plugins.title,
    workflows: t.workflows.title,
  };
  return COMMUNITY_SECTIONS.map((id) => ({
    id,
    label: labels[id],
    href: localePath(locale, PATHS[id]),
    count: id === "shares" ? shareCount(counts.shares) : counts[id],
  }));
}
