import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 社区页头的 tab 列表 —— 只由 (locale, counts) 决定。
 *
 * **社区就是「插件」和「工作流」两件事**:维护者:「插件和工作流本身就是分享的呀,官方插件和工作流就是官方
 * 账号发布分享的」。所以**不为「分享」单开一个 tab** —— 那会让同一样东西在导航里出现两次。
 *
 * **这个函数故意不收 `active`。** 旧实现把一项写成 `...(active === "x" ? [...] : [])`:切到别的页时
 * 那一项整个从页头消失,用户看到的就是「列表没了」—— 数据一直在,消失的只是入口。把当前页面挡在函数签名
 * 之外,这类「按页面裁剪导航」的写法就从结构上不可能再出现;高亮由页头自己拿 `active` 比对(见 community-header.tsx)。
 *
 * `/community` 是社区首页(插件 / 工作流 / 创意画板三段落地页),它不占 tab —— 各段的「查看全部」指向各自的市场页。
 * 三个市场页(插件 / 工作流 / 创意画板)平级,各占一个 tab;画布那一页没有官方静态内容,但**入口必须在**,
 * 否则用户上传的画布分享只能靠首页那一段出现。
 */
export const COMMUNITY_SECTIONS = ["plugins", "workflows", "boards"] as const;

export type CommunitySection = (typeof COMMUNITY_SECTIONS)[number];

/**
 * 页头 tab 上的数字。**画布的数拿不到就不传**(画布分享只在浏览器里取,服务端渲染时不知道)——
 * 页头的规则是"拿不到就不显示数字",不编一个 0 出来。
 */
export type CommunityCounts = {
  plugins: number;
  workflows: number;
  boards?: number;
};

export type CommunityTab = { id: CommunitySection; label: string; href: string; count?: number };

const PATHS: Record<CommunitySection, string> = {
  plugins: "/plugins",
  workflows: "/workflows",
  boards: "/boards",
};

export function communityTabs(locale: Locale, counts: CommunityCounts): CommunityTab[] {
  const t = getMessages(locale);
  const labels: Record<CommunitySection, string> = {
    plugins: t.plugins.title,
    workflows: t.workflows.title,
    boards: t.boards.title,
  };
  return COMMUNITY_SECTIONS.map((id) => ({
    id,
    label: labels[id],
    href: localePath(locale, PATHS[id]),
    count: counts[id],
  }));
}
