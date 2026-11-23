import { useQuery } from "@tanstack/react-query";

import { getJob, type Job } from "@/api/client";
import { jobKeys } from "@/api/queryKeys";
import { jobSettled } from "@/components/jobs/runStatus";

/**
 * 盯一个后台任务:按 `interval` 毫秒问一次详情,落了终态就不再问。**盯任务只有这一种写法。**
 *
 * 此前八处各写一个 useQuery:间隔从 700 到 2000 毫秒不等,「结束了没有」有的问 `jobSettled`、有的问自己的 TERMINAL / ACTIVE 集合,
 * 同一个任务还挂在两种键下(`["job", id]` 与 `["jobs", "workbench", id]`),一处拿到的新状态另一处看不见。
 * 现在键是 `jobKeys.detail(id)`(谁先拿到、别处一起用),停不停只看 `jobSettled`。
 *
 * `interval: false`:只取一次详情(要 `result`、不需要盯)。`enabled` 为假时什么都不问。
 */
export function useJob(
  jobId: string | null | undefined,
  {
    interval = 1000,
    enabled = true,
    initialData,
    refetchOnWindowFocus,
  }: { interval?: number | false; enabled?: boolean; initialData?: Job; refetchOnWindowFocus?: boolean } = {},
) {
  return useQuery({
    queryKey: jobKeys.detail(jobId),
    queryFn: () => getJob(jobId as string),
    enabled: enabled && Boolean(jobId),
    initialData,
    refetchOnWindowFocus,
    refetchInterval: (query) => (interval === false || jobSettled(query.state.data?.status) ? false : interval),
  });
}
