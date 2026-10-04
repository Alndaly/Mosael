import React from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

import { getJob, type Job, type WorkflowLibrary, type WorkflowNodePack } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

/**
 * 补齐缺的节点(ADR 0035 §5):装了 ComfyUI-Manager(V4)的连接,没装的节点包旁边「装上」—— 一个后台任务(`node_install`),
 * 经 Manager 装进那台机器的 custom_nodes;装完、或者装了却没加载的,要重启 ComfyUI 才加载,「重启 ComfyUI」也经 Manager。
 * 两样都改动那台机器,界面上都先确认(见 WorkflowLibraryDialog)。没装 Manager 就说在那台机器上手动装。
 */

const ACTIVE = new Set(["queued", "running"]);

/** 一个装节点包的任务装的是哪几个包。 */
export const packsOf = (job: Job): string[] => {
  const packs = (job.payload as Record<string, unknown> | undefined)?.packs;
  return Array.isArray(packs) ? packs.map(String) : [];
};

const subjectOf = (job: Job) => String((job.payload as Record<string, unknown> | undefined)?.subject ?? packsOf(job).join("、"));

export const installActive = (job: Job) => ACTIVE.has(job.status);

/** 装好了、还没重启过的(`restartedAt`:这次打开之后最近一次重启成功的时刻,毫秒;没重启过是 0)。 */
export const awaitingRestart = (job: Job, restartedAt: number) => {
  if (job.status !== "succeeded") return false;
  const finished = Date.parse(job.updated_at ?? "");
  return Number.isNaN(finished) || finished > restartedAt;
};

/**
 * 这个连接的装节点包任务:工作流库列着的那几次 + 这次打开之后发起的;在跑的每隔一会儿问一次进度。
 */
export function useNodeInstalls(library: WorkflowLibrary | undefined, started: Job[]): Job[] {
  const known = React.useMemo(() => {
    //: 列表重新列过之后,它带的那一份比「发起时」的那一份新:先认它的
    const listed = library?.installs ?? [];
    const ids = new Set(listed.map((job) => job.id));
    return [...started.filter((job) => !ids.has(job.id)), ...listed];
  }, [library, started]);
  const watching = known.filter(installActive).map((job) => job.id);
  const live = useQuery({
    queryKey: ["node-installs", watching],
    queryFn: () => Promise.all(watching.map((id) => getJob(id))),
    enabled: watching.length > 0,
    refetchInterval: 1500,
  });
  const fresh = new Map((live.data ?? []).map((job) => [job.id, job]));
  return known.map((job) => fresh.get(job.id) ?? job);
}

/**
 * 「缺的节点」那一节底下的一块:没装 Manager 的说法、这张工作流的节点包装到哪了(进度 / 装好了 / 没装成的原话)、
 * 要不要「重启 ComfyUI」(装好了的、装了却没加载的)。
 */
export function NodeInstallNote({
  manager,
  jobs,
  restartedAt,
  packs,
  restarting,
  restartError,
  onRestart,
}: {
  /** ComfyUI-Manager 的版本;没装是空串 */
  manager: string;
  /** 和这张工作流缺的节点包有关的那几次(这次打开之后发起的,和别处还在跑的) */
  jobs: Job[];
  restartedAt: number;
  /** 这张工作流缺的节点可能出自的节点包 */
  packs: WorkflowNodePack[];
  restarting: boolean;
  restartError: string;
  onRestart: () => void;
}) {
  const t = useI18n();
  //: 装好了、重启过的那几次不再说「重启之后才加载」:还缺的话,就是下面那句「装了却没加载」
  const shown = jobs.filter((job) => job.status !== "succeeded" || awaitingRestart(job, restartedAt));
  const installedNow = shown.some((job) => job.status === "succeeded");
  const notLoaded = packs.some((pack) => pack.installed);
  const restartable = Boolean(manager) && (installedNow || notLoaded);
  if (manager && !shown.length && !restartable && !restarting && !restartError) return null;
  return (
    <div className="grid min-w-0 gap-2 border-t border-border pt-2 text-ui-xs text-muted-foreground">
      {!manager && <p className="m-0 leading-relaxed">{t("workflowInstallNoManager")}</p>}
      {shown.map((job) => (
        <div key={job.id} className="grid min-w-0 gap-1">
          <span className="text-foreground">
            {t(job.status === "succeeded" ? "workflowInstallDone" : job.status === "failed" ? "workflowInstallFailed"
              : "workflowInstallRunning").replace("{name}", subjectOf(job))}
          </span>
          {installActive(job) && <Progress value={Math.round((job.progress ?? 0) * 100)} className="h-1.5" />}
          {job.status === "failed" && job.error && (
            <p className="m-0 whitespace-pre-line break-words leading-relaxed text-destructive">{job.error}</p>
          )}
        </div>
      ))}
      {restartable && (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {!installedNow && <span className="min-w-0 flex-1 leading-relaxed">{t("workflowInstalledNotLoaded")}</span>}
          <Button variant="outline" size="sm" loading={restarting} onClick={onRestart}>
            <RotateCw size={13} />
            {t("workflowRestart")}
          </Button>
        </div>
      )}
      {restarting && <p role="status" className="m-0">{t("workflowRestarting")}</p>}
      {restartError && <p role="alert" className="m-0 whitespace-pre-line break-words text-destructive">{restartError}</p>}
    </div>
  );
}
