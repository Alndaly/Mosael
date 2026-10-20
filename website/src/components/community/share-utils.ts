/**
 * 社区分享页的纯逻辑:字节数、文件名、登录回跳。
 *
 * 放在 `.ts`(没有 JSX)里有两个原因:**前端和 node 测试都能直接 import**,而且这些规则
 * 不该散落在各个组件里 —— 后端量的是「紧凑 JSON 的 UTF-8 字节数」,前端拦 2MB 时量的
 * 必须是同一把尺子,不然会出现「前端说没超、后端回 413」。
 */
import type { CloudIdentity, CloudSharePage } from "@/lib/cloud";

/** 后端 `MAX_PAYLOAD_BYTES` 的同一数值(2 MB)。 */
export const MAX_SHARE_BYTES = 2 * 1024 * 1024;

/** 列表一页的条数。后端默认 20,这里取 24 让三列网格排满。 */
export const SHARE_PAGE_SIZE = 24;

/** 列表的筛选条件。服务端首屏和客户端翻页用的是同一个形状。 */
export type ShareListQuery = { q: string; kind: "" | "workflow" | "board"; sort: "new" | "hot" };

/** 地址栏里那三个参数。App Router 的单值参数可能被写重成数组,这里只认第一个。 */
export type ShareQueryParams = {
  q?: string | string[];
  kind?: string | string[];
  sort?: string | string[];
};

function firstValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

/**
 * 地址栏 → 筛选条件。**不认识的值一律回落到默认**,别把 `?kind=evil` 带进请求。
 *
 * 首屏和分享出去的链接走这条;客户端改筛选走 shareSearch,两边是同一对函数 —— 刷新前后
 * 看到的结果才会一致。
 */
export function parseShareQuery(params: ShareQueryParams): ShareListQuery {
  const kind = firstValue(params.kind);
  return {
    q: firstValue(params.q).trim().slice(0, 200),
    kind: kind === "workflow" || kind === "board" ? kind : "",
    sort: firstValue(params.sort) === "hot" ? "hot" : "new",
  };
}

/**
 * 筛选条件 → 地址栏查询串(`""` 或 `?q=…&kind=…&sort=…`)。
 *
 * 默认值不写进地址栏(`sort=new`、`kind=` 都是默认),这样 `/community` 本身就是干净的;
 * 非默认值一个都不能丢 —— 分享出去的链接要能还原同一份结果。
 */
export function shareSearch(query: ShareListQuery): string {
  const params = new URLSearchParams();
  if (query.q.trim()) params.set("q", query.q);
  if (query.kind) params.set("kind", query.kind);
  if (query.sort !== "new") params.set("sort", query.sort);
  const suffix = params.toString();
  return suffix ? `?${suffix}` : "";
}

/**
 * 分享标签页上该显示的数字 —— **只有真知道总数时才返回**。
 *
 * 列表接口给的是游标分页,没有 total:取完一页还有 `next_cursor` 时总数是未知的;带着
 * `q` / `kind` 取到的只是筛选后的子集,更不能当总数。0 条也不显示 0(见 community-tabs)。
 */
export function knownShareCount(
  query: ShareListQuery,
  page: Pick<CloudSharePage, "items" | "next_cursor"> | null,
): number | undefined {
  if (!page) return undefined;
  if (page.next_cursor) return undefined;
  if (query.q.trim() || query.kind) return undefined;
  return page.items.length > 0 ? page.items.length : undefined;
}

/**
 * 「去上传」归谁:**列表非空归页头,列表为空归空态**,任何一屏都只出现一次。
 *
 * 两处各写一遍判断迟早会漂(这次就是页头 + 空态同时出现);写成一个函数,页面和测试读的是
 * 同一条规则。
 */
export function uploadCtaSurface(hasShares: boolean): "header" | "empty" {
  return hasShares ? "header" : "empty";
}

/** 登录回跳暂存在 sessionStorage:只活在这个标签页,关掉就没了。 */
export const COMMUNITY_RETURN_KEY = "mosael:community-return";

/**
 * 只留公开身份三列。
 *
 * `/me` 会连邮箱一起回(那是「自己的」账号信息),但把它交给客户端组件、写进 RSC 数据,
 * 就等于把一个不该出现在页面里的字段塞进了 HTML。所有要跨到客户端的身份都先过这里。
 */
export function publicIdentity(user: {
  display_name?: string | null;
  handle?: string | null;
  avatar_seed?: string | null;
}): CloudIdentity {
  return {
    display_name: typeof user.display_name === "string" ? user.display_name : null,
    handle: typeof user.handle === "string" ? user.handle : null,
    avatar_seed: typeof user.avatar_seed === "string" ? user.avatar_seed : null,
  };
}

/** 紧凑 JSON 的 UTF-8 字节数 —— 和后端 `payload_bytes` 的计算方式一致。 */
export function measurePayload(payload: unknown): number {
  const encoded = JSON.stringify(payload);
  if (encoded === undefined) return 0;
  return new TextEncoder().encode(encoded).length;
}

/**
 * 下载文件名:标题的 slug + `.json`。
 *
 * 保留各语言的字(中文标题不必变成 `mosael-share`),只把空白和标点折成连字符。
 * 60 个字符封顶,避免某些文件系统截断后少了扩展名。
 */
export function shareFilename(title: string): string {
  const slug = Array.from(
    title
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, ""),
  )
    .slice(0, 60)
    .join("")
    .replace(/-+$/g, "");
  return `${slug || "mosael-share"}.json`;
}

/** 文件大小。和卡片 / 详情里显示的一致,别在两处各写一套换算。 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB"] as const;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

/**
 * 分享的发布时间。**固定用 UTC**:同一个字符串在服务端和客户端算出来必须一样,
 * 否则 hydration 会报不一致(两种时区里「今天」可能不是同一天)。
 */
export function formatShareDate(iso: string, locale: "en" | "zh"): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

/** 登录页地址,带上「登录后回哪儿」。只接受站内社区路径(见 isCommunityReturnPath)。 */
export function communityLoginHref(locale: string, next: string): string {
  return `/${locale}/login?next=${encodeURIComponent(next)}`;
}

/**
 * 站内绝对路径、不带协议。
 *
 * 放宽成「任何站内路径」的话,`?next=` 就成了一个开放跳转口子(别人可以把登录页当跳板)。
 * 这里连协议相对地址(`//host`)和带协议的绝对地址一起挡掉。
 */
function isLocalPath(next: string | null | undefined): next is string {
  if (typeof next !== "string" || !next.startsWith("/")) return false;
  return !next.startsWith("//") && !next.includes("\\") && !next.includes("://");
}

/** 登录回跳只允许回社区页。 */
export function isCommunityReturnPath(next: string | null | undefined, locale: string): next is string {
  if (!isLocalPath(next)) return false;
  const base = `/${locale}/community`;
  return next === base || next.startsWith(`${base}/`) || next.startsWith(`${base}?`);
}

/** 「我的」控制台也是私有入口:从那里被踢去登录,登录完要能回来。 */
export function isDashboardReturnPath(next: string | null | undefined, locale: string): next is string {
  if (!isLocalPath(next)) return false;
  const base = `/${locale}/dashboard`;
  return next === base || next.startsWith(`${base}/`) || next.startsWith(`${base}?`);
}

/** 登录页唯一该接受的回跳集合:社区页 + 控制台。两者都不带协议、不跨语言。 */
export function isLoginReturnPath(next: string | null | undefined, locale: string): next is string {
  return isCommunityReturnPath(next, locale) || isDashboardReturnPath(next, locale);
}
