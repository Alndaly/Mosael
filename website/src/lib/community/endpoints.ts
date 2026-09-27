/**
 * 社区服务的路径,全站只在这里拼。
 *
 * 前缀 `/api/community/v1` 之后的部分逐条对着 ADR 0026「API 约定」。**ADR 里没有、官网又确实
 * 要用的接口**单独放在 `REQUESTED` 里 —— 那是提给社区服务的需求,服务没实现之前,对应的按钮会
 * 拿到 404,页面照常显示错误信息而不是崩掉。
 */
import { ASSET_KINDS, SORT_KEYS, type ItemKind, type SortKey } from "@/lib/community/types";

export const API_PREFIX = "/api/community/v1";

/** 列表每页条数:三列网格排满八行。 */
export const PAGE_SIZE = 24;

type Query = Record<string, string | number | undefined | null>;

export function withQuery(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

/** `workflow` → `/workflows`,`plugin` → `/plugins`,`asset` → `/assets`:三类条目的接口同形,只差这一段。 */
export function collection(kind: ItemKind): "/workflows" | "/plugins" | "/assets" {
  return kind === "workflow" ? "/workflows" : kind === "plugin" ? "/plugins" : "/assets";
}

export type ListQuery = {
  q?: string;
  tag?: string;
  sort?: SortKey;
  author?: string;
  cursor?: string | null;
  limit?: number;
  /** 只对资产:人物 / 场景 / 道具。 */
  asset_kind?: string;
};

const seg = encodeURIComponent;

export const ENDPOINTS = {
  auth: {
    smsSend: "/auth/sms/send",
    smsLogin: "/auth/sms/login",
    register: "/auth/register",
    passwordLogin: "/auth/password/login",
    passwordReset: "/auth/password/reset",
    refresh: "/auth/refresh",
    logout: "/auth/logout",
    deviceApprove: "/auth/device/approve",
  },
  me: {
    self: "/me",
    password: "/me/password",
    sessions: "/me/sessions",
    session: (id: string) => `/me/sessions/${seg(id)}`,
    submissions: "/me/submissions",
    shares: "/me/shares",
  },
  items: {
    list: (kind: ItemKind, query: ListQuery = {}) => withQuery(collection(kind), query),
    detail: (kind: ItemKind, slug: string) => `${collection(kind)}/${seg(slug)}`,
    versions: (kind: ItemKind, slug: string) => `${collection(kind)}/${seg(slug)}/versions`,
    create: (kind: ItemKind) => collection(kind),
    newVersion: (kind: ItemKind, slug: string) => `${collection(kind)}/${seg(slug)}/versions`,
    download: (kind: ItemKind, slug: string) => `${collection(kind)}/${seg(slug)}/download`,
    like: (kind: ItemKind, slug: string) => `${collection(kind)}/${seg(slug)}/like`,
  },
  shares: {
    detail: (slug: string) => `/shares/${seg(slug)}`,
  },
  stats: {
    overview: "/stats/overview",
    timeseries: (metric: string, days: number) => withQuery("/stats/timeseries", { metric, days }),
  },
  users: {
    profile: (handle: string) => `/users/${seg(handle)}`,
  },
  admin: {
    queue: "/admin/queue",
    approve: (id: string) => `/admin/submissions/${seg(id)}/approve`,
    reject: (id: string) => `/admin/submissions/${seg(id)}/reject`,
    /** kind 取 `workflow` / `plugin` / `share`。 */
    hide: (kind: ItemKind | "share", slug: string) => `/admin/items/${seg(kind)}/${seg(slug)}/hide`,
    reports: "/admin/reports",
  },
} as const;

/**
 * ADR 0026 的接口表里没有、官网要用的接口 —— 社区服务已经实现了,但应当补进 ADR(见提交说明)。
 *
 * - `report`:ADR §4 说「举报 → 进审核队列」,也有 `GET /admin/reports`,但没有列提交举报的接口。
 * - `publicShares`:ADR §5 说 `public` 画板「出现在作者主页和『画板』列表里」,但没有列出这份列表。
 * - `authConfig`:协议版本号与人机验证的 AppId,登录页要知道(否则只能在构建期写死)。
 * - `dismissReport`:举报看过、不需要下架时关掉它。
 */
export const REQUESTED = {
  report: (kind: ItemKind | "share", slug: string) => `${kind === "share" ? "/shares" : collection(kind)}/${seg(slug)}/report`,
  authConfig: "/auth/config",
  dismissReport: (id: string) => `/admin/reports/${seg(id)}/dismiss`,
  publicShares: (query: { author?: string; cursor?: string | null; limit?: number } = {}) => withQuery("/shares", query),
} as const;

/** 浏览器里用的完整地址(同源,经反代或 dev 的 rewrite 到社区服务)。 */
export function browserUrl(path: string): string {
  return `${API_PREFIX}${path}`;
}

/** 列表页 URL 上的 `?q&tag&sort` → 查询参数。认不出的 sort 回到默认的「热门」。 */
export function parseListQuery(search: Record<string, string | string[] | undefined>): {
  q: string;
  tag: string;
  sort: SortKey;
  asset_kind: string;
} {
  const one = (value: string | string[] | undefined) => (typeof value === "string" ? value.trim().slice(0, 100) : "");
  const sort = one(search.sort);
  const assetKind = one(search.asset_kind);
  return {
    q: one(search.q),
    tag: one(search.tag),
    sort: (SORT_KEYS as readonly string[]).includes(sort) ? (sort as SortKey) : "trending",
    //: 只对资产列表有意义;认不出的值当没给(服务端会拒,页面不该因为一个手改的 URL 报错)。
    asset_kind: (ASSET_KINDS as readonly string[]).includes(assetKind) ? assetKind : "",
  };
}
