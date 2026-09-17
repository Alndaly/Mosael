import React from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Job } from "@/api/client";

const isSettled = (status: string | undefined) => status === "succeeded" || status === "failed";

/**
 * 盯着一个刚排上的任务,到终态时回调一次。
 *
 * 合成、配音都是后台任务:点下去的那一刻界面上什么都不会变,产物要等它跑完才出现。
 * **得有人盯着** —— 不盯的话用户看到的是「点了没反应」,新素材、新音轨也不会自己冒出来。
 * 此前配音面板和字幕配音各写了一份(一份 setTimeout 自转,一份 useQuery),行为还不一样。
 */
export function useWatchedJob(onSettled: (job: Job) => void) {
  const [jobId, setJobId] = React.useState<string | null>(null);
  const callback = React.useRef(onSettled);
  callback.current = onSettled;
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => (isSettled(query.state.data?.status) ? false : 1000),
  });
  React.useEffect(() => {
    if (!jobId || job.data?.id !== jobId || !isSettled(job.data.status)) return;
    callback.current(job.data);
    setJobId(null);
  }, [jobId, job.data]);
  return { watch: setJobId, running: jobId !== null };
}
