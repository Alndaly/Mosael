/**
 * 全站查询键。**只在这一个文件里定义**。
 *
 * 组件里一律写 `queryKeys.xxx()`,不写裸数组:`invalidateQueries` 的匹配靠的是数组前缀,
 * 键散在业务代码里时,「改了昵称要刷哪几份缓存」就只能靠全局搜字符串找,漏一处就是
 * 「改了没生效」—— 站头还挂着旧昵称,而页面其他地方已经新了。
 *
 * 每个键都留**分组前缀**:
 * - `sharesByMe()`(不带 handle)匹配所有人的「我的分享」,改资料 / 退出时一次刷完;
 * - `shareList()` / `shareList(kind)` 匹配全部列表 / 某一 kind 的所有语言列表。
 */
import type { Locale } from "@/i18n/config";

/** 会在列表里混进用户分享的两种官方 kind(见 `components/community/listed-shares.ts`)。 */
export type ShareListKind = "plugin" | "workflow";

/** 登录态(`/me`)。站头、个人页、账号页读的是同一条缓存。 */
const viewer = () => ["viewer"] as const;

export const queryKeys = {
  /** `/me` —— 站头(公开三列)、个人页(还要邮箱)、账号页共用。 */
  viewer,
  /**
   * 个人页。**不另开一份 /me**:profile 指回 viewer,同一份数据只有一个来源,
   * 改资料时 invalidate 一次就同时刷新站头与个人页。
   */
  profile: viewer,
  /** 站头角标:`/notifications/unread-count`。 */
  unread: () => ["notifications", "unread"] as const,
  /** 通知分区:`/notifications`(游标翻页)。 */
  notifications: () => ["notifications", "list"] as const,
  /**
   * 通知的**整组前缀**(未读角标 + 通知列表)。评论新增 / 删除会让作者那边多一条通知,
   * 两处一起标脏;单点刷新请用 `unread()` / `notifications()`。
   */
  notificationsAll: () => ["notifications"] as const,
  /** 第三方登录按钮的可用性(`/oauth/providers`)。 */
  oauthProviders: () => ["oauth", "providers"] as const,
  /** 某个人的公开分享(控制台的「我的分享」)。不传 handle = 分组前缀。 */
  sharesByMe: (handle?: string | null) =>
    handle ? (["shares", "by-me", handle] as const) : (["shares", "by-me"] as const),
  /** 列表页追加的用户分享,按 kind + 语言分开缓存。不传 = 分组前缀。 */
  shareList: (kind?: ShareListKind, locale?: Locale) =>
    kind
      ? locale
        ? (["shares", "list", kind, locale] as const)
        : (["shares", "list", kind] as const)
      : (["shares", "list"] as const),
} as const;
