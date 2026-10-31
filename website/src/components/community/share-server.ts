/**
 * 社区页的服务端取数。**只在 server component 里 import。**
 *
 * 官网的会话是第一方 HttpOnly cookie(见 `lib/cloud.ts` 的说明),服务端渲染读得到它:
 * 把请求带来的 cookie 原样转给 Cloud 的 `/me` / `/shares`,就同时拿到「我是谁」和
 * `liked_by_me` / `favorited_by_me`。**不猜 cookie 名字** —— 部署时 `CLOUD_COOKIE_NAME`
 * 可以改,转发整袋 cookie 比写死一个名字稳。
 */
import { cache } from "react";
import { cookies } from "next/headers";

import {
  CLOUD_API,
  CloudApiError,
  cloudForServer,
  sumShareStats,
  type CloudCommentPage,
  type CloudIdentity,
  type CloudShare,
  type CloudShareStats,
} from "@/lib/cloud";

import { publicIdentity } from "./share-utils";

/** 服务端直连 Cloud 的内网地址。和 `next.config.ts` 的 rewrite 目标同一个环境变量。 */
function serverCloudBase(): string {
  return (process.env.CLOUD_API_URL || "http://127.0.0.1:8901").replace(/\/+$/, "");
}

/** 本次请求带来的 cookie,拼成 `Cookie` 头的值。 */
export async function cookieHeader(): Promise<string> {
  const jar = await cookies();
  return jar
    .getAll()
    .map((entry) => `${entry.name}=${entry.value}`)
    .join("; ");
}

export function serverCloud(cookie = "") {
  return cloudForServer({ baseUrl: serverCloudBase(), cookie });
}

/**
 * 单条分享。`cache` 让 `generateMetadata` 和页面本身共用同一次请求 —— 同一页不向云端问两遍。
 * `cookie` 参与缓存键:登录与游客拿到的 `liked_by_me` 不是同一个答案。
 */
export const loadShare = cache(async (id: string, cookie: string): Promise<CloudShare> => {
  return serverCloud(cookie).shares.get(id);
});

/**
 * 分享的 payload(工程文件本体)。**只在详情页要画预览时调用**;列表和详情本身都不取内容。
 *
 * 云端是 `GET /shares/{id}/payload` → `{ payload }`(见 `cloud/src/cloud/api/shares.py`)。
 * `lib/cloud.ts` 的客户端目前只包了 `/download`,这里直接走同一条服务端腿 —— 地址 / cookie
 * 的拼法和 `serverCloud` 一致。失败就抛出去,调用处把「没有预览」当成正常情况(页面其余部分
 * 照常),不在这里吞成空对象 —— 那会把「取失败」和「payload 就是空」混成同一个答案。
 *
 * `cache` + `cookie` 同 `loadShare`:一次渲染里只向云端问一遍。
 */
export const loadSharePayload = cache(async (id: string, cookie: string): Promise<unknown> => {
  let response: Response;
  try {
    response = await fetch(`${serverCloudBase()}${CLOUD_API}/shares/${encodeURIComponent(id)}/payload`, {
      headers: cookie ? { cookie } : {},
      // 和 lib/cloud.ts 的 request 一样:分享内容可能刚被作者改过,不能拿构建期的缓存。
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch {
    throw new CloudApiError(
      "network_error",
      { en: "Can't reach MosaelCloud. Check your connection and try again.", zh: "连不上 MosaelCloud，请检查网络后重试。" },
      0,
    );
  }

  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const error = body !== null && typeof body === "object" ? (body as { error?: unknown }) : {};
    throw new CloudApiError(
      typeof error.error === "string" ? error.error : "request_failed",
      { en: "That share's content could not be loaded.", zh: "这条分享的内容没有取到。" },
      response.status,
    );
  }
  // `{ payload: ... }` 是云端的契约;200 但不是这个形状,就当作「没有可预览的内容」。
  if (body === null || typeof body !== "object" || !("payload" in body)) {
    throw new CloudApiError(
      "invalid_payload",
      { en: "That share has no previewable content.", zh: "这条分享没有可预览的内容。" },
      response.status,
    );
  }
  return (body as { payload: unknown }).payload;
});

/** 评论第一页。读评论是公开接口,不需要会话。 */
export const loadComments = cache(async (id: string): Promise<CloudCommentPage> => {
  return serverCloud().shares.comments(id, { limit: 30 });
});

/** 一页最多 50 条(Cloud 的 `MAX_LIMIT`);控制台按页把一个人的分享全部取齐再求和。 */
const USER_SHARE_PAGE_LIMIT = 50;

/** 求和 / 列表最多翻这么多页。上限只是防止一个异常账号把 SSR 拖住,不是业务上限。 */
const MAX_USER_SHARE_PAGES = 10;

/**
 * 某人**已公开**的分享,取齐(按页翻到没有 `next_cursor` 为止)。
 *
 * 「我的」控制台的概览直接对这批数据的 `stats` 求和(见 `sumShareStats`),所以这里必须
 * 尽量取全,不能只拿第一页就把数字当总数。**只用已有的 `GET /users/{handle}/shares`** ——
 * 它只回 listed 的公开分享,和别的访客看到的完全一致;没有为控制台另开接口。
 */
/** 公开主页的身份。只回公开四列(display_name / handle / avatar_seed / official)。 */
export const loadPublicIdentity = cache(
  async (handle: string, cookie: string): Promise<CloudIdentity> => {
    const { user } = await serverCloud(cookie).profile.byHandle(handle);
    return user;
  },
);

export const loadUserShares = cache(
  async (handle: string, cookie: string): Promise<{ shares: CloudShare[]; totals: CloudShareStats }> => {
    const client = serverCloud(cookie);
    const shares: CloudShare[] = [];
    let cursor: string | null = null;
    for (let page = 0; page < MAX_USER_SHARE_PAGES; page += 1) {
      const result = await client.shares.byUser(handle, {
        limit: USER_SHARE_PAGE_LIMIT,
        ...(cursor ? { cursor } : {}),
      });
      shares.push(...result.items);
      cursor = result.next_cursor;
      if (!cursor) break;
    }
    return { shares, totals: sumShareStats(shares) };
  },
);

/**
 * 当前登录者(公开三列)。401 是「没登录」,不是错误;网络 / 服务端故障则抛出去,
 * 让上传页显示可重试的失败,而不是把已登录的人当成游客踢去登录。
 */
export async function loadViewer(cookie = ""): Promise<CloudIdentity | null> {
  try {
    const { user } = await serverCloud(cookie).account.me();
    return publicIdentity(user);
  } catch (error) {
    if (error instanceof CloudApiError && error.status === 401) return null;
    throw error;
  }
}
