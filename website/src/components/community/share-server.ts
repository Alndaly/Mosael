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
  CloudApiError,
  cloudForServer,
  type CloudCommentPage,
  type CloudIdentity,
  type CloudShare,
  type CloudSharePage,
} from "@/lib/cloud";

import { publicIdentity, SHARE_PAGE_SIZE, type ShareListQuery } from "./share-utils";

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

/** 列表第一页。 */
export const loadShareList = cache(async (query: ShareListQuery, cookie: string): Promise<CloudSharePage> => {
  return serverCloud(cookie).shares.list({
    q: query.q,
    kind: query.kind || undefined,
    sort: query.sort,
    limit: SHARE_PAGE_SIZE,
  });
});

/** 评论第一页。读评论是公开接口,不需要会话。 */
export const loadComments = cache(async (id: string): Promise<CloudCommentPage> => {
  return serverCloud().shares.comments(id, { limit: 30 });
});

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
