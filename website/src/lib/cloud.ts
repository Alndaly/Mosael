/**
 * MosaelCloud 的客户端 + 服务端取数封装。
 *
 * **浏览器只打同源的 `/api/cloud/v1/*`** —— 生产由 Caddy 把这个前缀转给 cloud 服务,本地开发由
 * `next.config.ts` 的 rewrite 转给 `CLOUD_API_URL`。同源有两个直接好处:会话 cookie 是第一方的,
 * 不需要 CORS + `SameSite=None`;云端那侧的 Origin 校验认的就是官网自己的地址。
 *
 * 会话 token 由服务端放在 HttpOnly cookie 里,**客户端拿不到、也不该拿**。所以浏览器这一侧没有
 * localStorage、没有 Authorization 头 —— 只有 `fetch` 默认带着的同源 cookie。
 *
 * 服务端渲染时不能靠浏览器的 cookie jar:调 `cloudForServer({ baseUrl, cookie })` 拿一个
 * 「显式把 cookie 头带上、直连 Cloud 内网地址」的客户端。**仍然是同一个 request 实现**,
 * 没有第二套 fetch。
 */

export const CLOUD_API = "/api/cloud/v1";

/**
 * 公开身份三列,**没有 email** —— 公开响应里本来就不带它。
 *
 * `official` 是官方账号的公开徽章(只有部署脚本会写 true),分享卡片用它标「官方」;
 * 它不参与身份校验,也不改变任何读接口的可见范围。
 */
export type CloudIdentity = {
  display_name: string | null;
  handle: string | null;
  avatar_seed: string | null;
  official?: boolean;
};

export type CloudUser = {
  id: string;
  email: string;
  email_verified_at: string | null;
  created_at: string;
  display_name?: string | null;
  handle?: string | null;
  avatar_seed?: string | null;
};

export type CloudMessage = { en: string; zh: string };

/** 分享类型。`plugin` 和插件市场里的静态条目是同一件东西。 */
export type CloudShareKind = "workflow" | "board" | "plugin";

/** 分享标题 / 简介的语言。云端只认这两种;`POST /shares` 必填。 */
export type CloudShareLocale = "zh-CN" | "en-US";

/**
 * 站点语言 → 云端分享语言。
 *
 * 路由段是短码(`/en` `/zh`),云端存的是 BCP 47(`en-US` / `zh-CN`);列表取数必须显式带
 * 后者 —— 不传的话云端两种都返回,英文站就会看到中文分享。
 */
export function cloudLocale(locale: "en" | "zh"): CloudShareLocale {
  return locale === "zh" ? "zh-CN" : "en-US";
}

export type CloudShareStats = {
  downloads: number;
  likes: number;
  favorites: number;
  comments: number;
};

export type CloudShare = {
  id: string;
  /**
   * 官方内容的稳定标识(来自 seed bundle 的 slug);**用户分享是 null**。
   *
   * 官网用它把云端分享对回静态详情页:`/plugins/<slug>` / `/workflows/<slug>` 已经有了,
   * 列表里就不再重复渲染一张分享卡片。
   */
  slug: string | null;
  kind: CloudShareKind;
  /** 这一行标题 / 简介的语言,不是 payload 的语言。 */
  locale: CloudShareLocale;
  title: string;
  summary: string | null;
  bytes: number;
  license: string | null;
  created_at: string;
  author: CloudIdentity;
  stats: CloudShareStats;
  liked_by_me: boolean;
  favorited_by_me: boolean;
};

/** 一件分享都没有时的统计。**全 0 是真实结果**,不是占位符。 */
export const ZERO_SHARE_STATS: CloudShareStats = {
  downloads: 0,
  likes: 0,
  favorites: 0,
  comments: 0,
};

/**
 * 把若干条分享的 `stats` 加起来。
 *
 * 「我的」控制台概览上的五个数字只有这一个来源:云端在 `/users/{handle}/shares` 里已经算好
 * 每条分享的下载 / 点赞 / 收藏 / 评论,这里只是求和 —— 不另开统计接口、不猜、不补 0。
 * 纯函数:浏览器、服务端和 node 测试跑的是同一份逻辑。
 */
export function sumShareStats(shares: ReadonlyArray<Pick<CloudShare, "stats">>): CloudShareStats {
  const total: CloudShareStats = { ...ZERO_SHARE_STATS };
  for (const share of shares) {
    total.downloads += Number(share.stats?.downloads) || 0;
    total.likes += Number(share.stats?.likes) || 0;
    total.favorites += Number(share.stats?.favorites) || 0;
    total.comments += Number(share.stats?.comments) || 0;
  }
  return total;
}

export type CloudSharePage = { items: CloudShare[]; next_cursor: string | null };

export type CloudComment = {
  id: string;
  share_id: string;
  body: string;
  created_at: string;
  author: CloudIdentity;
};

export type CloudCommentPage = { items: CloudComment[]; next_cursor: string | null };

/** 通知的三种来由。 */
export type CloudNotificationKind = "like" | "favorite" | "comment";

/** 被通知的那条分享 —— 只够画一行,详情要点进去。 */
export type CloudNotificationShare = { id: string; title: string; kind: CloudShareKind };

/**
 * 一条通知。`actor` 就是公开身份三列(`CloudIdentity`),**没有 email**。
 *
 * `comment_preview` 只在 `kind === "comment"` 时出现,是后端按字符截断的**纯文本**,
 * 不是 markdown —— 前端原样当文字渲染。
 */
export type CloudNotification = {
  id: string;
  kind: CloudNotificationKind;
  read_at: string | null;
  created_at: string;
  actor: CloudIdentity;
  share: CloudNotificationShare;
  comment_preview?: string;
};

export type CloudNotificationPage = {
  items: CloudNotification[];
  next_cursor: string | null;
  /** **未读总数**,不是本页未读数。 */
  unread: number;
};

/**
 * 顶栏角标上的数字:0 条未读不显示(`null`),超过 99 收成 `99+`。
 *
 * 纯函数放这里,顶栏和 node 测试跑的是同一份;不在组件里另写一遍取整 / 截断。
 */
export function formatUnreadBadge(count: number): string | null {
  const value = Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
  if (value === 0) return null;
  return value > 99 ? "99+" : String(value);
}

export type CloudNotificationQuery = { limit?: number; cursor?: string };

export type CloudShareInput = {
  kind: CloudShareKind;
  /** 发布时"自己的语言"由当前语言段明确声明;云端缺这个字段会回 422。 */
  locale: CloudShareLocale;
  title: string;
  summary?: string;
  payload: unknown;
  license?: string;
};

export type CloudShareQuery = {
  q?: string;
  kind?: string;
  /** 省略 = 云端两种语言都返回。按语言取数时**必须**带上。 */
  locale?: CloudShareLocale;
  sort?: string;
  limit?: number;
  cursor?: string;
};

const NETWORK_MESSAGE: CloudMessage = {
  en: "Can't reach MosaelCloud. Check your connection and try again.",
  zh: "连不上 MosaelCloud，请检查网络后重试。",
};

const FALLBACK_MESSAGE: CloudMessage = {
  en: "That didn't work. Try again.",
  zh: "操作没有完成，请重试。",
};

/** 云端的一次拒绝。`message` 是中英两份,页面按当前语言挑。 */
export class CloudApiError extends Error {
  // 用显式字段而不是构造器参数属性:Node 的 type-stripping 测试要直接 import 这个模块,
  // 参数属性属于"需要编译"的 TS 语法,strip-only 模式会拒绝。
  readonly code: string;
  readonly messages: CloudMessage;
  readonly status: number;

  constructor(code: string, messages: CloudMessage, status: number) {
    super(messages.en);
    this.name = "CloudApiError";
    this.code = code;
    this.messages = messages;
    this.status = status;
  }

  text(locale: "en" | "zh"): string {
    return this.messages[locale] || this.messages.en;
  }
}

function messageOf(value: unknown): CloudMessage {
  if (value && typeof value === "object" && "en" in value && "zh" in value) {
    const found = value as { en?: unknown; zh?: unknown };
    if (typeof found.en === "string" && typeof found.zh === "string") {
      return { en: found.en, zh: found.zh };
    }
  }
  return FALLBACK_MESSAGE;
}

/**
 * 一次请求的落点。浏览器不传 `context`(同源、带 cookie);服务端传 `baseUrl` + `cookie`
 * —— 直连 Cloud,不走公网回环。
 */
type RequestContext = { baseUrl?: string; cookie?: string };

function apiBase(context: RequestContext): string {
  if (!context.baseUrl) return CLOUD_API;
  return `${context.baseUrl.replace(/\/+$/, "")}${CLOUD_API}`;
}

async function request<T>(path: string, init: RequestInit = {}, context: RequestContext = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (context.cookie) headers.set("cookie", context.cookie);

  let response: Response;
  try {
    response = await fetch(`${apiBase(context)}${path}`, {
      ...init,
      // 同源请求本来就带 cookie;写出来是让"会话在 cookie 里"这件事在调用处可见。
      // 服务端那条腿把 cookie 显式放进请求头,Node 的 fetch 不理会 credentials(浏览器概念)。
      credentials: "same-origin",
      cache: "no-store",
      headers,
    });
  } catch {
    throw new CloudApiError("network_error", NETWORK_MESSAGE, 0);
  }

  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new CloudApiError(
      typeof body.error === "string" ? body.error : "request_failed",
      messageOf(body.message),
      response.status,
    );
  }
  return body as T;
}

function queryString(query: CloudShareQuery): string {
  const search = new URLSearchParams();
  if (query.q) search.set("q", query.q);
  if (query.kind) search.set("kind", query.kind);
  if (query.locale) search.set("locale", query.locale);
  if (query.sort) search.set("sort", query.sort);
  if (query.limit) search.set("limit", String(query.limit));
  if (query.cursor) search.set("cursor", query.cursor);
  const value = search.toString();
  return value ? `?${value}` : "";
}

/**
 * 同一个客户端的两条腿:账号(登录 / 会话)与社区(分享 / 互动)。
 *
 * 工厂而不是两份对象:服务端只是换一个 `baseUrl` / `cookie` 的来源,方法名、类型和错误语义
 * 必须完全一致,否则「浏览器能点、首屏渲染却挂」这种错会藏在两套代码的缝里。
 */
function createClient(context: RequestContext = {}) {
  return {
    account: {
      /** 哪些第三方登录已配置。官网只渲染 true 的那几颗按钮。 */
      oauthProviders(): Promise<{ providers: { github: boolean; google: boolean } }> {
        return request("/oauth/providers", {}, context);
      },
      sendSignupCode(email: string): Promise<{ sent: boolean }> {
        return request("/signup/code", { method: "POST", body: JSON.stringify({ email }) }, context);
      },
      signup(email: string, code: string, password: string): Promise<{ user: CloudUser }> {
        return request("/signup", { method: "POST", body: JSON.stringify({ email, code, password }) }, context);
      },
      login(email: string, password: string): Promise<{ user: CloudUser }> {
        return request("/login", { method: "POST", body: JSON.stringify({ email, password }) }, context);
      },
      sendLoginCode(email: string): Promise<{ sent: boolean }> {
        return request("/login/code", { method: "POST", body: JSON.stringify({ email }) }, context);
      },
      loginWithCode(email: string, code: string): Promise<{ user: CloudUser }> {
        return request("/login/code/verify", { method: "POST", body: JSON.stringify({ email, code }) }, context);
      },
      logout(): Promise<void> {
        return request("/logout", { method: "POST" }, context);
      },
      me(): Promise<{ user: CloudUser }> {
        return request("/me", {}, context);
      },
      deleteAccount(): Promise<void> {
        return request("/me", { method: "DELETE" }, context);
      },
    },
    profile: {
      /** `PUT /me`:第一次设置昵称 / 短名时用。 */
      update(patch: { display_name?: string; handle?: string }): Promise<{ user: CloudUser }> {
        return request("/me", { method: "PUT", body: JSON.stringify(patch) }, context);
      },
    },
    shares: {
      list(query: CloudShareQuery = {}): Promise<CloudSharePage> {
        return request(`/shares${queryString(query)}`, {}, context);
      },
      get(id: string): Promise<CloudShare> {
        return request(`/shares/${encodeURIComponent(id)}`, {}, context);
      },
      /** 下载:**只有这里**把工程文件取出来,并且让 downloads +1。 */
      download(id: string): Promise<{ payload: unknown }> {
        return request(`/shares/${encodeURIComponent(id)}/download`, { method: "POST" }, context);
      },
      create(input: CloudShareInput): Promise<{ share: CloudShare }> {
        return request("/shares", { method: "POST", body: JSON.stringify(input) }, context);
      },
      remove(id: string): Promise<void> {
        return request(`/shares/${encodeURIComponent(id)}`, { method: "DELETE" }, context);
      },
      like(id: string, liked: boolean): Promise<void> {
        return request(`/shares/${encodeURIComponent(id)}/like`, { method: liked ? "POST" : "DELETE" }, context);
      },
      favorite(id: string, favorited: boolean): Promise<void> {
        return request(`/shares/${encodeURIComponent(id)}/favorite`, {
          method: favorited ? "POST" : "DELETE",
        }, context);
      },
      comments(id: string, query: { limit?: number; cursor?: string } = {}): Promise<CloudCommentPage> {
        const search = new URLSearchParams();
        if (query.limit) search.set("limit", String(query.limit));
        if (query.cursor) search.set("cursor", query.cursor);
        const suffix = search.toString();
        return request(`/shares/${encodeURIComponent(id)}/comments${suffix ? `?${suffix}` : ""}`, {}, context);
      },
      createComment(id: string, body: string): Promise<{ comment: CloudComment }> {
        return request(`/shares/${encodeURIComponent(id)}/comments`, {
          method: "POST",
          body: JSON.stringify({ body }),
        }, context);
      },
      deleteComment(id: string, commentId: string): Promise<void> {
        return request(
          `/shares/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}`,
          { method: "DELETE" },
          context,
        );
      },
      byUser(handle: string, query: { limit?: number; cursor?: string } = {}): Promise<CloudSharePage> {
        const search = new URLSearchParams();
        if (query.limit) search.set("limit", String(query.limit));
        if (query.cursor) search.set("cursor", query.cursor);
        const suffix = search.toString();
        return request(`/users/${encodeURIComponent(handle)}/shares${suffix ? `?${suffix}` : ""}`, {}, context);
      },
    },
    notifications: {
      /** 本人的通知,新序在前;`unread` 是未读**总数**,不是本页条数。 */
      list(query: CloudNotificationQuery = {}): Promise<CloudNotificationPage> {
        const search = new URLSearchParams();
        if (query.limit) search.set("limit", String(query.limit));
        if (query.cursor) search.set("cursor", query.cursor);
        const suffix = search.toString();
        return request(`/notifications${suffix ? `?${suffix}` : ""}`, {}, context);
      },
      /** 顶栏角标只需要这个数字。 */
      unreadCount(): Promise<{ count: number }> {
        return request("/notifications/unread-count", {}, context);
      },
      /**
       * 标记已读。**不传 `ids` = 全部标已读**;`ids: []` = 一条都不标。
       *
       * 所以「全部」这条路径必须真的不带 body —— 传 `{}` 也好(后端把 `ids` 当 None),
       * 但传 `[]` 是另一件事。
       */
      markRead(ids?: string[]): Promise<{ marked: number; unread: number }> {
        return request(
          "/notifications/read",
          ids === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify({ ids }) },
          context,
        );
      },
    },
  };
}

const browser = createClient();

export const cloudAccount = browser.account;
export const cloudProfile = browser.profile;
export const cloudShares = browser.shares;
export const cloudNotifications = browser.notifications;

/**
 * 服务端渲染用的客户端。
 *
 * 只给 server component 用:显式带 cookie(而不是浏览器自动带),并直连 `CLOUD_API_URL`
 * 指的内网地址。**不要在客户端组件里调用它** —— 那会把服务端地址带进浏览器包。
 */
export function cloudForServer(options: { baseUrl: string; cookie?: string }): ReturnType<typeof createClient> {
  return createClient(options);
}
