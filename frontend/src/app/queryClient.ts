import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/transport";
import { createMutationCache } from "@/app/mutationErrors";
import type { MessageKey } from "@/app/messages";

/**
 * 查询失败要不要再试一次。
 *
 * **服务端明确拒绝的(4xx)不再试**:404(那样东西不在了)、403(没权限)、409 / 422(请求本身不对),再问一遍答案一样,
 * 只是让人多等一秒(默认的重试间隔)才看到「已删除或无法访问」—— 实测点开一篇被删的笔记,`GET /api/notes/<id>` 在 0.33 s
 * 和 1.34 s 各 404 一次。此前全局是 `retry: 1`,十九处查询各自手写 `retry: false` 躲开它。
 * 例外是 408(超时)和 429(限流):那两种过一会儿再问可能就好了。
 *
 * 断网、5xx、超时这些说不准的,照旧再试一次。
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) {
    return false;
  }
  return failureCount < 1;
}

/**
 * 整个应用那一个 QueryClient。
 *
 * 页面是条件挂载(切页整棵卸载/重挂),默认 staleTime:0 会让每次切页都重拉 → 首帧空态闪一下。
 * 给个合理缓存窗口:短时间切回同页直接用缓存,不重拉不闪;需要实时的 query 各自设了 refetchInterval,
 * 不受影响。获焦不全量重拉(Electron 频繁获焦会加剧闪烁)。
 */
export function createAppQueryClient(report: (message: string) => void, t: (key: MessageKey) => string): QueryClient {
  return new QueryClient({
    mutationCache: createMutationCache(report, t),
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: shouldRetryQuery,
      },
    },
  });
}
