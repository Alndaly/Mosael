import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Pin, Square } from "lucide-react";

import { assetThumbnailUrl, cancelJob, refreshPluginInstance, runCanvas, type Job } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { markOnlyResult } from "@/features/plugins/workbench/canvasMarks";
import { liveProgress, nodeLabels, outputGroups } from "@/features/plugins/workbench/workbenchLogic";
import { PanelNote, jobDone, useJobWatch } from "@/features/plugins/workbench/workbenchParts";
import {
  WorkbenchCallError,
  exportCanvas,
  rememberRun,
  type WorkbenchRun,
  type WorkbenchTarget,
} from "@/features/plugins/workbench/workbenchSession";

/**
 * 跑画布上现在这张(ADR 0038 §6,含没存的改动):经桥导出(API 格式 + 界面格式 + 前端的 clientId),建一个普通的生成任务
 * (模型 = 这张工作流,图在任务的载荷里)。新存的那张宿主的目录还没刷新到就刷新一次再试。
 */
export function useCanvasRun(target: WorkbenchTarget | null) {
  return useMutation({
    mutationFn: async (path: string) => {
      if (!target) throw new WorkbenchCallError("closed");
      const exported = await exportCanvas();
      const body = { workspace_id: target.workspaceId, path, prompt: exported.prompt, workflow: exported.workflow,
                     client_id: exported.clientId };
      let created;
      try {
        created = await runCanvas(target.instanceId, body);
      } catch (error) {
        if ((error as { status?: number })?.status !== 422) throw error;
        // 刚在 ComfyUI 里存的那张:宿主的目录可能还没刷新到它 —— 重拉一次再试
        await refreshPluginInstance(target.instanceId);
        created = await runCanvas(target.instanceId, body);
      }
      rememberRun({ jobId: created.job.id, path, startedAt: Date.now(), labels: [...nodeLabels(exported.workflow)] });
      return created.job;
    },
  });
}

/**
 * 工作台的「运行与结果」面板:这次会话里跑的每一次 —— 进度(任务本身按轮询;画布上正在跑哪个节点、第几步看桥的事件)、取消、
 * 失败的原因;跑完的产出**按来自的节点分组、标节点名**(以插件读的历史为准),每组一个「以后只要这张」(标在画布上那个输出节点,
 * 存盘后生效)。
 */
export function RunPanel({
  target,
  runs,
  events,
  canMark,
  runError,
}: {
  target: WorkbenchTarget;
  runs: WorkbenchRun[];
  events: ComfyWorkbenchEvent[];
  canMark: boolean;
  runError: unknown;
}) {
  const t = useI18n();
  const live = liveProgress(events);
  return (
    <div className="grid gap-3">
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchRunHint")}</p>
      {Boolean(runError) && (
        <PanelNote tone="error">
          {runError instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", runError.message) : errorText(runError)}
        </PanelNote>
      )}
      {runs.length === 0 ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("workbenchRunEmpty")}</p>
      ) : (
        <ol aria-label={t("workbenchRuns")} className="m-0 grid list-none gap-3 p-0">
          {runs.map((run, index) => (
            <RunCard key={run.jobId} target={target} run={run} live={index === 0 ? live : null} canMark={canMark} />
          ))}
        </ol>
      )}
    </div>
  );
}

function RunCard({
  target,
  run,
  live,
  canMark,
}: {
  target: WorkbenchTarget;
  run: WorkbenchRun;
  live: ReturnType<typeof liveProgress>;
  canMark: boolean;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const job = useJobWatch(run.jobId).data as Job | undefined;
  const labels = React.useMemo(() => new Map(run.labels), [run.labels]);
  const groups = job?.status === "succeeded" ? outputGroups(job, labels) : [];
  const [marked, setMarked] = React.useState<string | null>(null);
  const mark = useMutation({
    mutationFn: (node: string) => markOnlyResult(target.instanceId, node),
    onSuccess: (_done, node) => setMarked(node),
  });
  const cancel = useMutation({ mutationFn: () => cancelJob(run.jobId) });
  const running = !jobDone(job);
  const nodeName = (node: string) => `${labels.get(node) || t("workbenchNode")} #${node}`;
  return (
    <li className="grid gap-2 rounded-lg border border-border p-2.5" data-run={run.jobId}>
      <div className="flex min-w-0 items-center gap-2 text-ui-xs">
        {running && <Loader2 size={13} aria-hidden className="shrink-0 animate-mosael-spin text-muted-foreground" />}
        <Truncate className="min-w-0 flex-1 font-medium text-foreground">{run.path}</Truncate>
        <span className="shrink-0 tabular-nums text-muted-foreground">{new Date(run.startedAt).toLocaleTimeString(locale)}</span>
        {running && (
          <Button variant="ghost" size="xs" className="shrink-0" loading={cancel.isPending} onClick={() => cancel.mutate()}>
            <Square size={11} />
            {t("workbenchRunCancel")}
          </Button>
        )}
      </div>
      {running && (
        <p role="status" className="m-0 text-ui-xs text-muted-foreground">
          {live?.node
            ? t("workbenchRunLive").replace("{node}", nodeName(live.node))
              .replace("{step}", live.max ? `${live.value}/${live.max}` : "")
            : job?.message || t("workbenchRunQueued")}
        </p>
      )}
      {job?.status === "failed" && <PanelNote tone="error">{job.error || t("workbenchRunFailed")}</PanelNote>}
      {job?.status === "cancelled" && <PanelNote>{t("workbenchRunCancelled")}</PanelNote>}
      {groups.map((group) => (
        <section key={group.node || "unknown"} aria-label={group.node ? nodeName(group.node) : t("workbenchRunUnknownNode")}
                 className="grid gap-1.5">
          <div className="flex min-w-0 items-center gap-2 text-ui-xs">
            <Truncate className="min-w-0 flex-1 text-muted-foreground">
              {group.node ? t("workbenchRunFrom").replace("{node}", nodeName(group.node)) : t("workbenchRunUnknownNode")}
            </Truncate>
            {group.node && canMark && (
              <Button variant="outline" size="xs" className="shrink-0" loading={mark.isPending && mark.variables === group.node}
                      aria-pressed={marked === group.node}
                      aria-label={t("workbenchRunOnlyThisLabel").replace("{node}", nodeName(group.node))}
                      onClick={() => mark.mutate(group.node)}>
                <Pin size={11} />
                {t("workbenchRunOnlyThis")}
              </Button>
            )}
          </div>
          <ul className="m-0 grid list-none grid-cols-3 gap-1.5 p-0">
            {group.assets.map((asset) => (
              <li key={asset}>
                <img src={assetThumbnailUrl(asset)} alt={t("workbenchRunOutputAlt").replace("{node}", nodeName(group.node))}
                     loading="lazy" className="aspect-square w-full rounded-md bg-secondary object-cover" />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {marked && <PanelNote>{t("workbenchRunMarked").replace("{node}", nodeName(marked))}</PanelNote>}
      {mark.isError && (
        <PanelNote tone="error">
          {mark.error instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", mark.error.message) : errorText(mark.error)}
        </PanelNote>
      )}
    </li>
  );
}
