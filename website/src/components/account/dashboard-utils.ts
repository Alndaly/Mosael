/**
 * 「我的」控制台的纯逻辑:tab 清单、地址、登录回跳、删完一条之后剩哪些。
 *
 * 放在 `.ts`(没有 JSX)里,前端与 `node --test` 能直接 import 同一份实现 —— 五个 tab 的地址
 * 是**可收藏、可分享的 URL**,不是组件里的一个 state;删掉一条分享之后概览的数字必须跟着变,
 * 这两件事都值得真的跑一遍,而不是渲染出来看。
 */
import type { CloudShare } from "@/lib/cloud";

/** 五个分区。顺序 = tab 栏的顺序;地址是 `?tab=` 的取值。 */
export const DASHBOARD_TABS = ["overview", "shares", "profile", "devices", "notifications"] as const;

export type DashboardTab = (typeof DASHBOARD_TABS)[number];

export function isDashboardTab(value: unknown): value is DashboardTab {
  return typeof value === "string" && (DASHBOARD_TABS as readonly string[]).includes(value);
}

/**
 * 把地址栏里的 `?tab=` 归一到已知分区。
 *
 * 非法值返回空串,由页面决定默认值 —— 这样 `?tab=whatever` 不会把页面变成 404,也不会
 * 悄悄停在某个分区上 pretending 用户选过它。
 */
export function normalizeDashboardTab(value: string | string[] | undefined): DashboardTab | "" {
  const first = Array.isArray(value) ? value[0] : value;
  return isDashboardTab(first) ? first : "";
}

/**
 * 首屏停在哪儿。
 *
 * 刚注册、还没起名字的账号没有 handle,概览无从统计 —— 直接停在「个人信息」,那里有一句
 * 「先起个名字」。**不把概览留白**:停在概览上却没数字,是最容易让人以为页面坏了的一种空。
 */
export function defaultDashboardTab(hasHandle: boolean): DashboardTab {
  return hasHandle ? "overview" : "profile";
}

/** 控制台里任意分区的地址(可以直接收藏 / 分享 / 新标签打开)。 */
export function dashboardTabHref(locale: string, tab: DashboardTab): string {
  return `/${locale}/dashboard?tab=${tab}`;
}

/**
 * 未登录时去登录页,并带「登录后回哪儿」。
 *
 * 和社区上传页同一套(见 `components/community/share-utils.ts` 与 `login-return.tsx`):
 * 登录表单成功后固定去 `/account`,那边确认会话建立后按 `next` 把用户送回来。
 * 这里指回控制台根地址,不带 tab —— 登录后按账号状态重新决定落在哪个分区。
 */
export function dashboardLoginHref(locale: string): string {
  return `/${locale}/login?next=${encodeURIComponent(`/${locale}/dashboard`)}`;
}

/** 删掉一条分享之后剩下的列表。不改原数组 —— 失败回滚和乐观更新都要靠这一点。 */
export function withoutShare(shares: ReadonlyArray<CloudShare>, id: string): CloudShare[] {
  return shares.filter((share) => share.id !== id);
}
