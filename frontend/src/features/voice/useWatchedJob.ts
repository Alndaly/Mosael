import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Job } from "@/api/client";

const isSettled = (status: string | undefined) => status === "succeeded" || status === "failed";

/**
 * 盯着一个刚排上的任务,在它跑完之前让发起的按钮保持忙碌。
 *
 * **它不报完成,也不刷新产物** —— 那两件事归任务中心(ADR-0018):任务目录声明了每种任务
 * 改动哪些数据、做完要不要说。此前这里的调用方各自弹一条"完成",任务中心又弹一条。
 * 排上的那一刻让任务列表立刻重取,任务中心才能看到它从"在跑"变成"结束"。
 */
export function useWatchedJob() {
  const qc = useQueryClient();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => (isSettled(query.state.data?.status) ? false : 1000),
  });
  React.useEffect(() => {
    if (jobId && job.data?.id === jobId && isSettled(job.data.status)) setJobId(null);
  }, [jobId, job.data]);
  const watch = React.useCallback(
    (id: string) => {
      setJobId(id);
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    [qc],
  );
  return { watch, running: jobId !== null };
}
