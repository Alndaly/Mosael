import React from "react";
import { useMutation } from "@tanstack/react-query";

import { cancelJob, getJob, urlSupport } from "@/api/client";
import { jobSettled } from "@/components/jobs/runStatus";
import { useI18n } from "@/app/preferences";

import type { PageInfo, PageToolsBridge } from "./pageActions";
import type { DownloadEntry } from "./VideoPanel";
import type { ToolNotice } from "./useToolNotice";
import { jobAssetId, startVideoDownload, type VideoCandidate, type VideoProbe } from "./videoActions";

const JOB_POLL_MS = 1_500;

/**
 * 下载页面里的视频:找(主进程看播放器和网络响应 + 后端看是不是平台页面)、下(排「从链接导入」任务)、
 * 跟进度、取消。任务在后端跑,任务中心里也看得到;这里每隔一会儿问一次,落定了在顶栏说一声。
 */
export function useVideoTools(
  tools: PageToolsBridge,
  workspaceId: string,
  page: PageInfo,
  profileId: () => Promise<string | null>,
  notice: ToolNotice,
) {
  const t = useI18n();
  const { say, failed, savedAsset } = notice;
  const [probe, setProbe] = React.useState<VideoProbe | null>(null);
  const [platform, setPlatform] = React.useState<string | null>(null);
  const [downloads, setDownloads] = React.useState<DownloadEntry[]>([]);

  const find = useMutation({
    mutationFn: async () => {
      const [found, support] = await Promise.all([
        tools.probeVideos(),
        urlSupport(workspaceId, page.url).catch(() => ({ supported: false, extractor: "" })),
      ]);
      return { found, support };
    },
    onMutate: () => setProbe(null),
    onSuccess: ({ found, support }) => {
      setProbe(found);
      setPlatform(support.supported ? support.extractor : null);
    },
    onError: failed,
  });

  const download = useMutation({
    mutationFn: async (candidate?: VideoCandidate) =>
      startVideoDownload({ workspaceId, page, profileId: await profileId(), candidate }),
    onSuccess: (job) => {
      setDownloads((list) => [{ jobId: job.id, title: page.title || page.url, status: "running", progress: job.progress ?? 0 }, ...list]);
      say({ tone: "busy", text: t("browserToolsDownloadQueued") });
    },
    onError: failed,
  });

  const cancel = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (_job, jobId) => {
      setDownloads((list) => list.map((entry) => (entry.jobId === jobId ? { ...entry, status: "cancelled" } : entry)));
      say({ tone: "done", text: t("browserToolsDownloadCancelled") });
    },
    onError: failed,
  });

  const running = downloads.filter((entry) => entry.status === "running").map((entry) => entry.jobId).join(",");
  React.useEffect(() => {
    if (!running) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      for (const jobId of running.split(",")) {
        void getJob(jobId)
          .then((job) => {
            if (stopped) return;
            const settled = jobSettled(job.status);
            setDownloads((list) =>
              list.map((entry) =>
                entry.jobId !== jobId || entry.status !== "running"
                  ? entry
                  : {
                      ...entry,
                      progress: job.progress ?? entry.progress,
                      status: settled ? (job.status as "succeeded" | "failed" | "cancelled") : "running",
                      error: job.error ?? undefined,
                    },
              ),
            );
            if (job.status === "succeeded") savedAsset(jobAssetId(job));
            else if (job.status === "failed") say({ tone: "error", text: t("browserToolsDownloadFailed").replace("{reason}", job.error ?? "") });
          })
          .catch(() => undefined);
      }
    }, JOB_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [running, savedAsset, say, t]);

  return {
    probe,
    platform,
    downloads,
    find,
    download,
    cancel,
    active: downloads.find((entry) => entry.status === "running") ?? null,
  };
}
