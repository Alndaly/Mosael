"use client";

/**
 * 站内共用的查询 hook。
 *
 * **同一份数据只经这一个入口取**:站头、个人页、账号页读的都是 `useViewer()` 那一份
 * `/me`;通知列表走 `useNotifications()`;控制台的「我的分享」走 `useMyShares()`
 * (服务端首屏数据作为 `initialData`,不重拉;失效后才重取)。
 *
 * 写操作不在这里包 mutation:hook 只负责读,写完之后由调用点按
 * `lib/query-invalidation.ts` 里那张清单点名 `invalidateQueries` —— 「刷哪几份缓存」
 * 才有唯一一处可查。
 */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  CloudApiError,
  cloudAccount,
  cloudNotifications,
  cloudShares,
  type CloudShare,
  type CloudUser,
} from "@/lib/cloud";
import { enabledOAuthProviders, type OAuthProviderName } from "@/lib/oauth";

import { queryKeys } from "./queryKeys";

/**
 * `/me`。401 是「没登录」而不是错误:返回 null,让站头去画「登录」按钮。
 * 其他失败照常抛给 query —— 重试策略在 `lib/query-client.ts` 里统一管。
 */
export async function fetchViewer(): Promise<CloudUser | null> {
  try {
    const { user } = await cloudAccount.me();
    return user;
  } catch (failure) {
    if (failure instanceof CloudApiError && failure.status === 401) return null;
    throw failure;
  }
}

/**
 * 我是谁。站头(首字母 / 色块 / aria-label)、个人页、账号页共用。
 * 改资料 / 登录 / 退出之后靠 `invalidateAfterProfileSave` 等把它标脏再重取。
 */
export function useViewer() {
  return useQuery({ queryKey: queryKeys.viewer(), queryFn: fetchViewer });
}

/** 站头角标。没登录 / 401 时是 0(角标就不出现),不因为一个数字把站头变成错误态。 */
export function useUnreadCount() {
  return useQuery({
    queryKey: queryKeys.unread(),
    queryFn: async () => {
      try {
        const { count } = await cloudNotifications.unreadCount();
        return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
      } catch (failure) {
        if (failure instanceof CloudApiError && failure.status === 401) return 0;
        throw failure;
      }
    },
  });
}

/** 通知一页的条数。后端默认 20,这里沿用。 */
export const NOTIFICATION_PAGE_SIZE = 20;

/**
 * 通知分区。游标翻页用 infinite query:同一份缓存,进分区不重拉(默认 staleTime),
 * 标已读后由 `invalidateAfterMarkRead` 刷新。**不轮询**。
 */
export function useNotifications(limit: number = NOTIFICATION_PAGE_SIZE) {
  return useInfiniteQuery({
    queryKey: queryKeys.notifications(),
    queryFn: ({ pageParam }) =>
      cloudNotifications.list({ limit, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** 控制台「我的分享」一次取多少条 / 最多翻几页(与 `share-server.ts` 同一套规则)。 */
const USER_SHARE_PAGE_LIMIT = 50;
const MAX_USER_SHARE_PAGES = 10;

/** 取齐某个人的公开分享(按页翻到没有 next_cursor 为止),概览的数字对它求和。 */
export async function fetchMyShares(handle: string): Promise<CloudShare[]> {
  const shares: CloudShare[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_USER_SHARE_PAGES; page += 1) {
    const result = await cloudShares.byUser(handle, {
      limit: USER_SHARE_PAGE_LIMIT,
      ...(cursor ? { cursor } : {}),
    });
    shares.push(...result.items);
    cursor = result.next_cursor;
    if (!cursor) break;
  }
  return shares;
}

/**
 * 「我的分享」+ 概览。服务端首屏已经把这份数据取回来了 —— 作为 `initialData` 接住,
 * 首屏不会再多打一次请求;删除 / 改资料后失效,才按新数据重取。
 *
 * `initialShares` 只在**它确实属于当前 handle** 时传(见 DashboardView):刚起完名字、
 * handle 变了的时候,拿旧的那份空数组当 initialData 会让新 key 被当成「一小时内都新鲜」,
 * 于是概览停在 0 不重取。传 undefined 就等于让这个 key 正常去问一次。
 */
export function useMyShares(handle: string, initialShares?: CloudShare[]) {
  return useQuery({
    queryKey: queryKeys.sharesByMe(handle),
    queryFn: () => fetchMyShares(handle),
    initialData: initialShares,
    enabled: Boolean(handle),
  });
}

/**
 * 第三方登录按钮的可用性。**没配置就整块不画**:请求失败也按没配置处理,
 * 不画一个点下去只会报错的按钮。
 */
export function useOAuthProviders() {
  return useQuery({
    queryKey: queryKeys.oauthProviders(),
    queryFn: async (): Promise<OAuthProviderName[]> => {
      try {
        return enabledOAuthProviders(await cloudAccount.oauthProviders());
      } catch {
        return [];
      }
    },
    // 部署配置不会在页面打开期间变:10 分钟内都算新鲜,登录 / 注册页之间切换不重拉。
    staleTime: 10 * 60_000,
    retry: false,
  });
}
