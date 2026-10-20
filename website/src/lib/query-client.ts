/**
 * QueryClient 的默认值。**理由都写在这里,组件里不再一份份调**。
 *
 * - `staleTime: 60_000` —— 一分钟内同一份数据算新鲜:切页、来回开 tab 不重拉,
 *   `/plugins`、`/workflows`、`/community` 之间来回走时列表不会每次闪一下;站头 /
 *   个人页 / 我的分享也靠它撑住,只有 `invalidateQueries` 会立刻让缓存失效。
 * - `refetchOnWindowFocus: true` —— 从后台切回来时刷一下。登录态(站头头像)、未读数、
 *   列表在别的标签页里可能已经变了;这一下比定时轮询便宜,也比一直不刷准确。
 * - `retry: retryUnlessUnauthorized` —— 401 是「你没登录」,重试一万次也不会变成已登录,
 *   只会多打几次 401;网络抖动 / 5xx 才值得重试,并且最多两次。
 */
import { QueryClient } from "@tanstack/react-query";

import { CloudApiError } from "./cloud";

/** 默认新鲜期:一分钟。见文件头的理由。 */
export const DEFAULT_STALE_TIME = 60_000;

/**
 * 是否值得再试一次。
 *
 * `401`(未登录)与 `403`(没权限)是确定的答案,重试不会改变结果 —— 站头 / 个人页
 * 在未登录时本来就会收到 401,	retrying 只会让「登录」按钮闪得比现在还慢。
 */
export function retryUnlessUnauthorized(failureCount: number, error: unknown): boolean {
  if (error instanceof CloudApiError && (error.status === 401 || error.status === 403)) return false;
  return failureCount < 2;
}

/** 每个浏览器会话一份 QueryClient(由 `app/[locale]/query-provider.tsx` 持有)。 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME,
        refetchOnWindowFocus: true,
        retry: retryUnlessUnauthorized,
      },
      // 写操作不做自动重试:PUT /me / POST /shares 重放一次可能就是「保存两次」。
      mutations: { retry: false },
    },
  });
}
