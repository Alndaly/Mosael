import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History, Loader2, Pin, Square, Undo2 } from "lucide-react";

import {
  assetFileUrl,
  assetPreviewUrl,
  assetThumbnailUrl,
  cancelJob,
  getCanvasApp,
  refreshPluginInstance,
  runCanvas,
  type Job,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import {
  FormsLockedError,
  markOnlyResult,
  readCanvasResults,
  unmarkResult,
  type CanvasResults,
} from "@/features/plugins/workbench/canvasMarks";
import { liveProgress, nodeLabels, outputGroups, runGallery, runsByWorkflow } from "@/features/plugins/workbench/workbenchLogic";
import { PANEL_ROOT, PanelEmpty, PanelNote, jobDone, useJobWatch } from "@/features/plugins/workbench/workbenchParts";
import {
  WorkbenchCallError,
  exportCanvas,
  nameRun,
  rememberRun,
  workbenchCall,
  type WorkbenchRun,
  type WorkbenchTarget,
} from "@/features/plugins/workbench/workbenchSession";
import { cn } from "@/lib/utils";

/**
 * 跑画布上现在这张(ADR 0038 §6,含没存的改动):经桥导出(API 格式 + 界面格式 + 前端的 clientId),建一个普通的生成任务
 * (模型 = 这张工作流,图在任务的载荷里)。新存的那张宿主的目录还没刷新到就刷新一次再试。记下跑的是画布上的哪一张。
 *
 * 和在 ComfyUI 里点「运行」一样:导出之前、任务建好之后各让桥走一遍前端自己的「生成后怎样」(runControls)—— 种子设成
 * randomize 的,连点两次运行此前用的是同一个存着的种子,出同一张图(沙盒实测)。桥做不了(主进程是旧的)不拦着跑。
 *
 * 节点叫什么:先记图里的标题(没起就是类型),同时问插件这张图每个节点给人看的名字(和应用表单、「结果取自」同一种叫法),
 * 到了就换上 —— 不等它才记下这一次,问不到就留着标题和类型。
 */
export function useCanvasRun(target: WorkbenchTarget | null) {
  return useMutation({
    mutationFn: async ({ path, workflowKey, workflowName }: { path: string; workflowKey: string; workflowName: string }) => {
      if (!target) throw new WorkbenchCallError("closed");
      await workbenchCall({ op: "runControls", phase: "before" });
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
      void workbenchCall({ op: "runControls", phase: "after" });
      const labels = nodeLabels(exported.workflow);
      rememberRun({ jobId: created.job.id, path, workflowKey, workflowName, kind: created.generation.kind ?? "image",
                    startedAt: Date.now(), labels: [...labels] });
      const jobId = created.job.id;
      void getCanvasApp(target.instanceId, exported.workflow)
        .then((app) => nameRun(jobId, [...labels, ...Object.entries(app.names ?? {})]))
        .catch(() => undefined);
      return created.job;
    },
  });
}

/** 结果标记那几样(只给画布上开着的这一张跑过的那几次):现在标着哪几个、正在改哪一个、改。 */
interface MarkControls {
  results: string[] | null;
  pending: string | null;
  mark: (node: string) => void;
  unmark: (node: string) => void;
}

/**
 * 工作台的「运行与结果」面板:这次会话里跑的每一次 —— 进度(任务本身按轮询;画布上正在跑哪个节点、第几步看桥的事件)、取消、
 * 失败的原因;跑完的产出**按来自的节点分组、标节点名**(以插件读的历史为准),点开看大图(这一次的全部产出成组翻)。
 *
 * 画布上开着的这一张跑过的排在前面;换过别的工作流跑的那几次收在「其他工作流」里,还看得到。
 *
 * **结果取自哪个节点**(ADR 0038 §5):每组一个「只要这个节点的图」—— 标的是**输出节点**(以后在 AI 工作台、画板、工作流节点里
 * 用这张工作流时只取它出的图),不是收藏这一张图。已经标着的那组写「结果取自这个节点」和「撤销」;标着的别的节点也说出来。
 * 标在画布上,存盘后生效。
 */
export function RunPanel({
  target,
  runs,
  events,
  workflowKey,
  active,
  canMark,
  runError,
}: {
  target: WorkbenchTarget;
  runs: WorkbenchRun[];
  events: ComfyWorkbenchEvent[];
  workflowKey: string;
  active: boolean;
  canMark: boolean;
  runError: unknown;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const live = liveProgress(events);
  const { current, others } = runsByWorkflow(runs, workflowKey);
  const resultsKey = React.useMemo(() => ["workbench-canvas-results", target.instanceId, workflowKey], [target.instanceId, workflowKey]);
  //: 标记在画布上:切回这个页签时重读(应用面板、ComfyUI 里都可能改过)
  const results = useQuery({
    queryKey: resultsKey,
    queryFn: () => readCanvasResults(target.instanceId),
    enabled: canMark && active && current.length > 0,
    staleTime: 0,
    retry: false,
  });
  const [changed, setChanged] = React.useState<{ node: string; undo: boolean } | null>(null);
  const change = useMutation({
    mutationFn: ({ node, undo }: { node: string; undo: boolean }) =>
      undo ? unmarkResult(target.instanceId, workflowKey, node) : markOnlyResult(target.instanceId, workflowKey, node),
    onMutate: () => setChanged(null),
    onSuccess: (next: CanvasResults, asked) => {
      qc.setQueryData(resultsKey, next);
      setChanged(asked);
    },
  });
  //: 换了一张工作流:上一张标没标成的那句话不是这一张的
  const resetChange = change.reset;
  React.useEffect(() => {
    setChanged(null);
    resetChange();
  }, [workflowKey, resetChange]);
  const labels = results.data?.labels ?? {};
  const labelOf = (node: string) => `${labels[node] || t("workbenchNode")} #${node}`;
  //: 这张的表单是上一版 / 更新版插件写的:标结果要重写整份标记,会把表单抹掉 —— 不给标,说去「表单」页签升级
  const locked = results.data?.lock ?? null;
  const marks: MarkControls | null = canMark && !locked ? {
    results: results.data?.results ?? null,
    pending: change.isPending ? change.variables?.node ?? null : null,
    mark: (node) => change.mutate({ node, undo: false }),
    unmark: (node) => change.mutate({ node, undo: true }),
  } : null;
  const marked = results.data?.results ?? [];

  return (
    <div className={cn(PANEL_ROOT, "gap-3")}>
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchRunHint")}</p>
      {Boolean(runError) && (
        <PanelNote tone="error">
          {runError instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", runError.message) : errorText(runError)}
        </PanelNote>
      )}
      {canMark && current.length > 0 && marked.length > 0 && (
        <p data-results-from="" className="m-0 flex min-w-0 items-center gap-1.5 text-ui-xs text-foreground">
          <Pin size={11} aria-hidden className="shrink-0 text-primary" />
          <Truncate>{t("workbenchRunResultsFrom").replace("{nodes}", marked.map(labelOf).join("、"))}</Truncate>
        </p>
      )}
      {locked && current.length > 0 && (
        <PanelNote tone="warning">
          <span data-results-locked="">
            {locked.upgradable ? t("workbenchRunFormsOld") : t("workbenchFormsNewer").replace("{version}", locked.version || "?")}
          </span>
        </PanelNote>
      )}
      {changed && (
        <PanelNote>
          {t(changed.undo ? "workbenchRunUnmarked" : "workbenchRunMarked").replace("{node}", labelOf(changed.node))}
        </PanelNote>
      )}
      {change.isError && (
        <PanelNote tone="error">
          {change.error instanceof FormsLockedError ? t("workbenchRunFormsOld")
            : change.error instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", change.error.message)
              : errorText(change.error)}
        </PanelNote>
      )}
      {current.length === 0 ? (
        <PanelEmpty icon={History}>{t(others.length > 0 ? "workbenchRunEmptyHere" : "workbenchRunEmpty")}</PanelEmpty>
      ) : (
        <ol aria-label={t("workbenchRuns")} className="m-0 grid list-none gap-3 p-0">
          {current.map((run, index) => (
            <RunCard key={run.jobId} run={run} live={index === 0 ? live : null} marks={marks} />
          ))}
        </ol>
      )}
      {others.length > 0 && <OtherRuns others={others} />}
    </div>
  );
}

/** 换过别的工作流跑的那几次:默认收着,一张工作流一组。 */
function OtherRuns({ others }: { others: ReturnType<typeof runsByWorkflow>["others"] }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const count = others.reduce((sum, one) => sum + one.runs.length, 0);
  return (
    <section aria-label={t("workbenchRunOthers")} className="grid gap-2 border-t border-border pt-3">
      <button
        type="button"
        aria-expanded={open}
        className="inline-flex cursor-pointer items-center gap-1 justify-self-start border-0 bg-transparent p-0 text-ui-xs font-medium text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
        {t("workbenchRunOthersToggle").replace("{n}", String(count))}
      </button>
      {open && others.map((group) => (
        <section key={group.key} aria-label={group.name} className="grid gap-2">
          <h3 className="m-0 text-ui-xs font-semibold text-foreground"><Truncate>{group.name}</Truncate></h3>
          <ol className="m-0 grid list-none gap-3 p-0">
            {group.runs.map((run) => <RunCard key={run.jobId} run={run} live={null} marks={null} />)}
          </ol>
        </section>
      ))}
    </section>
  );
}

function RunCard({
  run,
  live,
  marks,
}: {
  run: WorkbenchRun;
  live: ReturnType<typeof liveProgress>;
  marks: MarkControls | null;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { openImagePreview } = useImagePreview();
  const job = useJobWatch(run.jobId).data as Job | undefined;
  const labels = React.useMemo(() => new Map(run.labels), [run.labels]);
  const groups = job?.status === "succeeded" ? outputGroups(job, labels) : [];
  const cancel = useMutation({ mutationFn: () => cancelJob(run.jobId) });
  const running = !jobDone(job);
  const nodeName = (node: string) => `${labels.get(node) || t("workbenchNode")} #${node}`;
  const video = run.kind === "video";
  //: 这一次的全部产出成组翻(按回执里的顺序),标题带来源节点和第几张
  const gallery = runGallery(groups, nodeName, t("workbenchRunUnknownNode")).map((one) => ({
    src: video ? assetFileUrl(one.asset) : assetPreviewUrl(one.asset),
    title: one.title,
    video,
    asset: one.asset,
  }));
  const open = (asset: string) => {
    const at = gallery.find((one) => one.asset === asset);
    if (at) openImagePreview({ src: at.src, title: at.title, video, gallery: gallery.map(({ asset: _asset, ...item }) => item) });
  };
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
      {/* 这一次跑挂了:全应用那一份失败展示 —— ComfyUI 那句「执行到「KSampler」这一步出错」、认得出时的原因和升级命令、原话在「详情」里 */}
      {job?.status === "failed" && (
        <FailureCard title={t("workbenchRunFailed")} {...failureFields(job, t("workbenchRunFailed"))} data-workbench-run-failed={run.jobId} />
      )}
      {job?.status === "cancelled" && <PanelNote>{t("workbenchRunCancelled")}</PanelNote>}
      {groups.map((group) => {
        const name = group.node ? nodeName(group.node) : t("workbenchRunUnknownNode");
        const isResult = Boolean(group.node && marks?.results?.includes(group.node));
        return (
          <section key={group.node || "unknown"} aria-label={name} className="grid gap-1.5">
            <div className="flex min-h-7 min-w-0 items-center gap-2 text-ui-xs">
              <Truncate className="min-w-0 flex-1 text-muted-foreground">
                {group.node ? t("workbenchRunFrom").replace("{node}", name) : name}
              </Truncate>
              {group.node && marks && (isResult ? (
                <>
                  <span data-result-mark="" className="inline-flex shrink-0 items-center gap-1 font-medium text-primary">
                    <Pin size={11} aria-hidden />
                    {t("workbenchRunIsResult")}
                  </span>
                  <Button variant="ghost" size="xs" className="shrink-0" loading={marks.pending === group.node}
                          aria-label={t("workbenchRunUndoMarkLabel").replace("{node}", name)}
                          onClick={() => marks.unmark(group.node)}>
                    <Undo2 size={11} />
                    {t("workbenchRunUndoMark")}
                  </Button>
                </>
              ) : (
                <Hint label={t("workbenchRunOnlyThisHint").replace("{node}", name)}>
                  <Button variant="outline" size="xs" className="shrink-0" loading={marks.pending === group.node}
                          aria-label={t("workbenchRunOnlyThisLabel").replace("{node}", name)}
                          onClick={() => marks.mark(group.node)}>
                    <Pin size={11} />
                    {t("workbenchRunOnlyThis")}
                  </Button>
                </Hint>
              ))}
            </div>
            <ul className="m-0 grid list-none grid-cols-3 gap-1.5 p-0">
              {group.assets.map((asset) => {
                const title = gallery.find((one) => one.asset === asset)?.title ?? name;
                return (
                  <li key={asset}>
                    <IconButton
                      unstyled
                      label={t("workbenchPreviewOpen").replace("{title}", title)}
                      className="block w-full cursor-zoom-in rounded-md border-0 bg-transparent p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      onClick={() => open(asset)}
                    >
                      <img src={assetThumbnailUrl(asset)} alt={t("workbenchRunOutputAlt").replace("{node}", name)}
                           loading="lazy" className="block aspect-square w-full rounded-md bg-secondary object-cover" />
                    </IconButton>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </li>
  );
}
