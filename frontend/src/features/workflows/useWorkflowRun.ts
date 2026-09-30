import React from "react";
import { type QueryClient, useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  cancelJob,
  listJobEvents,
  listWorkflowRuns,
  runWorkflow,
  type Job,
  type TaskEvent,
  type Workflow,
  type WorkflowGraph,
  type WorkflowNodeType,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { useI18n } from "@/app/preferences";
import { issuesAtLayer } from "@/features/workflows/analyze";
import { boundRunId, RUN_ACTIVE, viewedRunId } from "@/features/workflows/boundRun";
import { useWorkflowAnalysis } from "@/features/workflows/readiness";
import { runEventIsTerminal, stepsByNode } from "@/features/workflows/runSteps";
import type { ScopePath } from "@/features/workflows/scope";
import type { WorkflowSaveState } from "@/features/workflows/useWorkflowSave";

/**
 * 编辑器里「运行」的那一半:画布绑着哪一次运行、正在看哪一次、它的每一步、运行 / 停止,
 * 以及运行前的就绪度分析。
 */
export function useWorkflowRun({
  workflow,
  qc,
  t,
  rootGraph,
  registry,
  scopePath,
  save,
  pendingSaveRef,
}: Pick<WorkflowSaveState, "save" | "pendingSaveRef"> & {
  workflow: Workflow;
  qc: QueryClient;
  t: ReturnType<typeof useI18n>;
  rootGraph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  scopePath: ScopePath;
}) {
  /** 自己在这一页点「运行」起的那次。运行完不清,方便回看这次跑成什么样;再次运行或切换工作流
   *  时被顶掉。 */
  const [startedJobId, setStartedJobId] = React.useState<string | null>(null);
  /** 用户在执行历史里点了哪一次(null = 没点过,跟随最新)。点「运行」、点「回到最新」都清掉它。 */
  const [pinnedRunId, setPinnedRunId] = React.useState<string | null>(null);
  React.useEffect(() => {
    setStartedJobId(null);
    setPinnedRunId(null);
  }, [workflow.id]);
  /** 这个工作流最近的几次运行。**不是为了历史面板**,是为了认出**别处发起的**那一次:
   *
   *  子工作流是被父流程的 `call_workflow` 起来的(它有自己的 job,见 executors/subworkflow),
   *  点进它的画布时这一页从没调用过 run,于是画布一个节点状态都没有、没有 loading —— 明明正在跑,
   *  看着像根本没开始。重开一个正在跑的工作流也是同一回事。
   *
   *  所以画布绑的是「自己起的那次 → 否则这个工作流最近的一次运行」。 */
  const runs = useQuery({
    queryKey: ["workflow-runs", workflow.id],
    queryFn: () => listWorkflowRuns(workflow.id),
    refetchIntervalInBackground: true,
    // 在跑就跟紧;没在跑也**保持一个慢轮询** —— 父流程可能几分钟后才走到调用这一步,
    // 而那时我们正开着它的画布等着看。停掉的话这一页永远等不到那次运行出现。
    refetchInterval: (q) =>
      ((q.state.data as Job[] | undefined) ?? []).some((one) => RUN_ACTIVE.has(one.status)) ? 2000 : 8000,
  });
  /** 跟随的那一次:自己起的 → 还在跑的 → 最近的(见 boundRun)。工具栏的运行 / 停止只看它。 */
  const runJobId = React.useMemo(() => boundRunId(startedJobId, runs.data), [startedJobId, runs.data]);
  /** **正在看哪一次运行 —— 只有这一个。** 画布上的节点状态、检查器的「本次产出」、执行历史的选中项
   *  都读它。此前历史面板自己记一份选中:在历史里点开一次旧的,画布和检查器还停在最近那次,
   *  三处说的是两次运行。 */
  const viewedRun = viewedRunId(pinnedRunId, runJobId, runs.data);
  const viewRun = React.useCallback(
    // 点的正是跟随着的那一次就等于「跟随」:之后再起一次运行,三处照样跟过去。
    (id: string | null) => setPinnedRunId(id === runJobId ? null : id),
    [runJobId],
  );
  const runEvents = useQuery({
    queryKey: ["job-events", viewedRun],
    queryFn: () => listJobEvents(viewedRun ?? ""),
    enabled: Boolean(viewedRun),
    // 窗口没聚焦也要继续轮询:把应用放在一边看着工作流跑是常态,默认行为会暂停轮询,
    // 于是回头一看画布还停在半小时前的那一步。
    refetchIntervalInBackground: true,
    // 跑动时勤快些,结束后停下来。判据是「有没有收尾事件」而不是 job 状态:
    // 后者要等整条流程收尾,中间那段画布就不动了。
    refetchInterval: (q) => {
      const list = (q.state.data as TaskEvent[] | undefined) ?? [];
      const done = list.some(runEventIsTerminal);
      return done ? false : 800;
    },
  });
  const runByNode = React.useMemo(() => stepsByNode(runEvents.data ?? []), [runEvents.data]);
  /** 绑定的那次运行**此刻还在跑吗** —— 工具栏据此在「运行」和「停止」之间切换。
   *  按 runs 列表里那一行的状态判,而不是 run.isPending:后者只覆盖"把任务排进队列"
   *  那一下(几十毫秒),排完就回 false,而工作流才刚开始跑。 */
  const running = (runs.data ?? []).some((one) => one.id === runJobId && RUN_ACTIVE.has(one.status));
  const stop = useMutation({
    mutationFn: () => cancelJob(runJobId!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflow.id] });
      void qc.invalidateQueries({ queryKey: ["job-events", runJobId] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error: Error) => toast.error(errorText(error)),
  });
  const run = useMutation({
    mutationFn: () => runWorkflow(workflow.id),
    onSuccess: (job) => {
      setStartedJobId(job.id);
      // 刚点的这一次就是要看的那一次 —— 哪怕刚才正停在一次旧运行上。
      setPinnedRunId(null);
      toast.success(t("wfRunQueued"));
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflow.id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });

  // 就绪度分析:和列表卡片的「运行」、检查器的提醒同一个判据(见 readiness / bindingReadiness)。
  // 喂画布角标(按当前这一层折,见 issuesAtLayer)和运行前的就绪清单。
  const analysis = useWorkflowAnalysis(rootGraph, registry);
  const layerIssues = React.useMemo(() => issuesAtLayer(analysis.issues, scopePath), [analysis.issues, scopePath]);
  /**
   * 运行 —— 工具栏的运行键和 ⌘Enter 共用这**一个**入口。
   *
   * 运行跑的是服务端存着的那一版。还有没存的改动就先存(复用同一条保存,和打开版本历史那条
   * 一样),存失败就不跑;就绪清单里有阻断问题就不跑。此前两个入口各写各的判据:运行键在
   * 「还没存完」和「有阻断问题」时是灰的,快捷键两条都没管 —— 改完立刻按 ⌘Enter,跑的是
   * 改之前的图。
   *
   * 运行键也只看这里的判据,不再看 dirty:自动保存撞上非 409 的错误后 dirty 一直是 true,
   * 运行键就一直灰着、说「保存中…」,而 ⌘Enter 这条能先重存再跑。
   *
   * 重入闸是 ref,不是 state:同一帧里连按两次 ⌘Enter,两次闭包读到的 state(和 run.isPending)
   * 都还是旧值,会排两次运行。ref 从进门一直关到「排进队列」这一步落定;`launching` 只管按钮转圈。
   */
  const launchingRef = React.useRef(false);
  const [launching, setLaunching] = React.useState(false);
  //: 就绪清单开没开。有阻断问题时按运行(⌘Enter;运行键这时是灰的)就把清单打开 —— 此前这一下
  //: 什么都不发生,按的人不知道是没按到、还是有问题、问题在哪。
  const [checklistOpen, setChecklistOpen] = React.useState(false);
  const startRun = React.useCallback(async () => {
    if (launchingRef.current || run.isPending) return;
    if (!analysis.runnable) {
      setChecklistOpen(true);
      return;
    }
    launchingRef.current = true;
    try {
      if (pendingSaveRef.current) {
        setLaunching(true);
        try {
          await save.mutateAsync();
        } catch {
          return;
        } finally {
          setLaunching(false);
        }
      }
      // 失败提示在 run 自己的 onError 里给,这里只等它落定再开闸。
      await run.mutateAsync().catch(() => undefined);
    } finally {
      launchingRef.current = false;
    }
  }, [run, save, analysis.runnable]);
  const checklistCount = analysis.errorCount + analysis.warnCount;
  const checklistLabel = analysis.errorCount
    ? t("wfChecklistBlocked").replace("{n}", String(analysis.errorCount))
    : analysis.warnCount
      ? t("wfChecklistWarnOnly").replace("{n}", String(analysis.warnCount))
      : t("wfChecklistReady");

  return {
    runJobId,
    viewedRun,
    viewRun,
    runByNode,
    running,
    stop,
    run,
    analysis,
    layerIssues,
    launching,
    startRun,
    checklistCount,
    checklistLabel,
    checklistOpen,
    setChecklistOpen,
  };
}

export type WorkflowRunState = ReturnType<typeof useWorkflowRun>;
