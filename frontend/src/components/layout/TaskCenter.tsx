import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, CircleAlert, ListChecks, Loader2, Trash2, X } from "lucide-react";

import { toast } from "sonner";

import { api, getJob, topLevelJobsQuery, type Job } from "@/api/client";
import { EmptyState } from "@/components/layout/EmptyState";
import { useI18n, usePreferences } from "@/app/preferences";
import { JobDetailDialog } from "@/components/layout/JobDetailDialog";
import { gotoJobPage, JobKindIcon, jobPage, queryKeysAffectedBy, shouldAnnounce, useJobKinds } from "@/components/layout/jobKinds";
import { relativeTime } from "@/lib/time";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LIST_HAIRLINE } from "@/components/ui/floating";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { isImeKeystroke } from "@/lib/shortcuts";

const ACTIVE = new Set(["queued", "running"]);

/** 任务总线的统一入口(计划 §12 / Phase 6):导出、转写、AI 生成、
 * 定时任务都在这一个面板里看进度;刷新后从 /api/jobs 直接恢复。 */
export function TaskCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  // 深链通道(与 mosael:open-* 约定一致):首页任务磁贴等入口用事件打开任务中心弹层。
  const [detailJob, setDetailJob] = React.useState<Job | null>(null);
  const { kindOf, ready: kindsReady } = useJobKinds();
  React.useEffect(() => {
    const onOpen = (event: Event) => {
      setOpen(true);
      // 带了 id 就直接翻到那一条。**按 id 现取,不在列表里找** —— 这里列的是 top_level,
      // 而最常想跟进的恰恰是工作流派生的子任务(某一镜的生成),它不在这个列表里。
      const jobId = (event as CustomEvent<string | undefined>).detail;
      if (typeof jobId !== "string" || !jobId) return;
      void getJob(jobId)
        .then(setDetailJob)
        // 取不到就只开面板 —— 任务可能已经被清掉了,而"点了没反应"比"开了个空弹窗"好。
        .catch(() => undefined);
    };
    window.addEventListener("mosael:open-tasks", onOpen);
    return () => window.removeEventListener("mosael:open-tasks", onOpen);
  }, []);

  const jobsQuery = topLevelJobsQuery(workspaceId);
  const jobs = useQuery({
    // 顶层:工作流派生的子任务(发布/导出/转写/生成/配音)收纳到父工作流下,
    // 不再与父工作流平铺成两行;子任务在工作流任务详情里查看。
    ...jobsQuery,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 1500 : 8000,
    refetchOnWindowFocus: true,
  });
  const clearFinished = useMutation({
    mutationFn: () => api(`/api/jobs/finished?workspace_id=${workspaceId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  });
  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: jobsQuery.queryKey }),
    onError: (error: Error) => toast.error(error.message),
  });

  const all = jobs.data ?? [];
  const active = all.filter((job) => ACTIVE.has(job.status));
  // 已结束的按「种类 + 对象 + 结果文本」收拢:同一个素材的代理转码失败重试了五次,
  // 是一件事发生了五次,不是五件事 —— 平铺成五行只会把别的任务挤出视野。
  // 代表取最新一条(点开看的详情、行上的时间都是它的),其余只留一个 ×N。
  const finished = React.useMemo(() => {
    const groups = new Map<string, { job: Job; count: number }>();
    for (const job of all.filter((item) => !ACTIVE.has(item.status))) {
      const subject = String((job.payload as Record<string, unknown> | null)?.subject ?? "");
      const key = `${job.kind}|${job.status}|${subject}|${job.error ?? job.message}`;
      const seen = groups.get(key);
      if (seen) seen.count += 1;
      else groups.set(key, { job, count: 1 });
    }
    return [...groups.values()].slice(0, 12);
  }, [all]);

  // 点任务行 → 打开该 job 的执行详情弹层(状态 + 事件时间线)。
  const openJob = (job: Job) => {
    setDetailJob(job);
    setOpen(false);
  };

  // 详情弹层里「前往对应页面」:去哪一页、打开哪条记录,由任务目录声明。
  const gotoDetailPage = (job: Job) => {
    gotoJobPage(job, kindOf(job.kind));
    setDetailJob(null);
  };

  // 把「有几个任务在跑」推给桌面端(托盘文案 + 有任务时阻止系统睡眠)。放这里是因为这个组件
  // 本来就在按活跃度自适应轮询 /api/jobs,不必为此再拉一个查询;也因为方向必须是「知道业务的
  // 这一侧告诉系统层」,而不是让主进程反过来查后端。
  // 进度取活跃任务的均值:Windows 任务栏进度条要一个 0..1。都还没报进度(全 0)时给 null,
  // 让系统层走不确定态 —— 显示 0% 会看起来像卡住了,而它其实只是还没开始报。
  const aggregateProgress = React.useMemo(() => {
    if (active.length === 0) return null;
    const sum = active.reduce((acc, job) => acc + (typeof job.progress === "number" ? job.progress : 0), 0);
    return sum > 0 ? sum / active.length : null;
  }, [active]);
  React.useEffect(() => {
    window.mosaelDesktop?.reportStatus?.({ runningJobs: active.length, progress: aggregateProgress });
  }, [active.length, aggregateProgress]);

  // 任务完成提示:只在「上一轮还在跑、这一轮结束了」的跃迁上弹一次,
  // 首次加载时只记录基线,避免刷新后把历史任务全部弹一遍。
  const prevStatuses = React.useRef<Map<string, string> | null>(null);
  // 说过「做完了」的任务。**一个任务最多说一次** —— 不管它之后在列表里消失又出现、还是被
  // 重新排队又做完一次。
  const announced = React.useRef<Set<string>>(new Set());
  // Reset the baseline when the workspace changes. Neither TaskCenter nor Studio is keyed, so
  // this ref survived the switch; the new workspace's jobs then all hit `prev === undefined`
  // and the "first seen already terminal" branch below toasted every one of them — a wall of
  // notifications for jobs that finished days ago, which is precisely what the baseline exists
  // to prevent.
  React.useEffect(() => {
    prevStatuses.current = null;
    announced.current = new Set();
  }, [workspaceId]);
  React.useEffect(() => {
    // 目录没到之前不记基线:不知道一种任务该不该说,就等它到了再开始看。
    if (!jobs.data || !kindsReady) return;
    if (prevStatuses.current === null) {
      prevStatuses.current = new Map(jobs.data.map((job) => [job.id, job.status]));
      return;
    }
    for (const job of jobs.data) {
      // 子任务由父任务替它说(ADR-0018),也不该出现在这份顶层列表里。它要是出现了,说明
      // 缓存被别的取法写过 —— 那正是此前一打开定时任务页,历史上每个工作流派生的转写、导出
      // 都被当成「刚做完」弹一遍的原因(见 api/domains/jobs 的 topLevelJobsQuery)。
      if (job.parent_job_id) continue;
      const prev = prevStatuses.current.get(job.id);
      const terminal = job.status === "succeeded" || job.status === "failed";
      prevStatuses.current.set(job.id, job.status);
      // Settled on this poll: active→terminal, or first seen already terminal (prev undefined).
      // A fast job (e.g. a workflow with a notify node) can go queued→done between two polls, so
      // it's never seen active — without the second case it would never be announced.
      if (!terminal || (prev !== undefined && !ACTIVE.has(prev))) continue;
      const meta = kindOf(job.kind);
      // **任务做完了,它改动的东西就得跟着刷新** —— 任务中心是唯一知道"哪个任务刚结束"的地方,
      // 所以放在这里一处,而不是每个页面各自轮询。失败也刷:部分成功时已经落地的产物同样得看得见
      // (字幕配音配好了一半)。
      for (const key of queryKeysAffectedBy(meta)) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
      // **只有这里说"做完了"**(ADR-0018)。发起任务的组件只说"排上了";子任务不在这个列表里,
      // 由父任务替它说。
      if (!shouldAnnounce(meta, job.status) || announced.current.has(job.id)) continue;
      announced.current.add(job.id);
      const outcome = job.status === "succeeded" ? t("jobDone") : t("jobFailed");
      const detail = (job.status === "failed" ? job.error : job.message) ?? undefined;
      if (job.status === "succeeded") toast.success(`${meta.label} · ${outcome}`, { description: detail });
      else toast.error(`${meta.label} · ${outcome}`, { description: detail });
      // 同一件事也告诉系统层。这里无条件调用、由主进程决定发不发:窗口收进托盘或切到别的
      // app 时,上面这个 toast 弹在一个看不见的窗口里等于没弹,那时才需要系统通知。
      window.mosaelDesktop?.notifyTask?.({ title: `${meta.label} · ${outcome}`, body: detail ?? "" });
    }
  }, [jobs.data, kindsReady, kindOf, t, qc]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="relative"
              aria-label={t("taskCenter")}
            >
              {active.length > 0 ? <Loader2 size={15} className="animate-mosael-spin" /> : <Activity size={15} />}
              {active.length > 0 && <em className="absolute -top-0.5 right-[-3px] h-3.5 min-w-3.5 rounded-full bg-action px-[3px] text-center text-[9.5px] font-bold not-italic leading-[14px] text-action-foreground">{active.length}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("taskCenter")}</TooltipContent>
      </Tooltip>

      {/* p-0:PopoverContent 基类自带 p-4,而里面的头部和列表各自已经有内边距 ——
          留着就是里外两层留白,行会被推得离弹层边缘很远。 */}
      <PopoverContent className="w-[min(440px,calc(100vw-24px))] overflow-hidden p-0" aria-label={t("taskCenter")}>
        <div className="flex items-center justify-between border-b border-divider px-5 py-5 [&_strong]:text-lg">
          <strong>{t("taskCenter")}</strong>
          {finished.length > 0 && (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-destructive"
              disabled={clearFinished.isPending}
              onClick={() => clearFinished.mutate()}
            >
              <Trash2 size={11} /> {t("clearEnded")}
            </button>
          )}
        </div>
        {/* `grid-cols-[minmax(0,1fr)]` 不是装饰:单列 grid 的隐式列是 `auto`,也就是 **max-content**
            —— 一条长提示词(AI 生成任务的 subject)会把这一列撑到内容宽度,整个弹层于是能左右滚,
            而行内那些 truncate 全都失效(它们要一个有定数的列宽才截得动)。 */}
        {/* 行间的线**不用 `divide-y`**:那会把它画成上一行的 border-bottom,而这些行带着
            `rounded-lg`(hover 高亮要圆角),border 跟着圆角走,横线两端就翘成弧。
            改成独立的 1px 块(LIST_HAIRLINE),线是直的,左右还能收进来一点。 */}
        <div className="grid max-h-[min(560px,70vh)] grid-cols-[minmax(0,1fr)] gap-0 overflow-y-auto overflow-x-hidden px-3 py-2">
          {active.map((job, index) => (
            <React.Fragment key={job.id}>
              {index > 0 && <div className={LIST_HAIRLINE} />}
              <JobRow job={job} onOpen={() => openJob(job)} onCancel={() => cancelJob.mutate(job.id)} />
            </React.Fragment>
          ))}
          {active.length > 0 && finished.length > 0 && <div className={LIST_HAIRLINE} />}
          {finished.map(({ job, count }, index) => (
            <React.Fragment key={job.id}>
              {index > 0 && <div className={LIST_HAIRLINE} />}
              <JobRow job={job} count={count} onOpen={() => openJob(job)} />
            </React.Fragment>
          ))}
          {all.length === 0 && (
            <EmptyState size="compact" icon={<ListChecks size={15} />} title={t("noJobsTitle")} body={t("noJobs")} />
          )}
        </div>
      </PopoverContent>
      <JobDetailDialog
        job={detailJob}
        onClose={() => setDetailJob(null)}
        onGoto={detailJob && jobPage(detailJob, kindOf(detailJob.kind)) ? () => gotoDetailPage(detailJob) : undefined}
      />
    </Popover>
  );
}

function JobRow({ job, count = 1, onOpen, onCancel }: { job: Job; count?: number; onOpen?: () => void; onCancel?: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const meta = useJobKinds().kindOf(job.kind);
  const running = ACTIVE.has(job.status);
  const failed = !running && job.status === "failed";
  const subject = String((job.payload as Record<string, unknown> | null)?.subject ?? "");
  return (
    <div
      className="grid cursor-pointer grid-cols-[36px_minmax(0,1fr)] items-start gap-3 rounded-lg px-2 py-4 hover:bg-secondary"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (isImeKeystroke(event)) return;
        if (event.key === "Enter") onOpen?.();
      }}
    >
      <span
        className={cn(
          "grid size-9 place-items-center rounded-lg bg-accent text-accent-foreground",
          failed && "bg-[color-mix(in_oklab,var(--destructive)_12%,var(--background))] text-destructive",
        )}
      >
        <JobKindIcon meta={meta} />
      </span>
      {/* 又一处单列 grid:`min-w-0` 管的是这个 div 自身的最小宽度,管不住**轨道** ——
          隐式列仍是 max-content,于是里面的 truncate 没有定数可截,内容直接顶出去。
          真机量到:容器已锁到 284px,而每一行的 scrollWidth 还有 992px。 */}
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-[3px]">
        <div className="flex items-center justify-between gap-1.5 [&_strong]:text-ui-sm [&_strong]:font-semibold">
          <span className="flex min-w-0 items-baseline gap-1.5">
            <strong className="shrink-0">{meta.label}</strong>
            {/* 干的是谁的活:素材名/序列名/提示词。没有它,一列失败全长一个样。 */}
            {subject && (
              <span className="min-w-0 truncate text-ui-xs text-muted-foreground" title={subject}>
                {subject}
              </span>
            )}
            {count > 1 && (
              <span className="shrink-0 rounded-full bg-secondary px-1.5 text-ui-2xs tabular-nums text-muted-foreground">
                ×{count}
              </span>
            )}
          </span>
          <span className="inline-flex shrink-0 items-center gap-1 text-ui-2xs tabular-nums text-muted-foreground">
            {!running && (
              <span title={job.updated_at}>{relativeTime(job.updated_at, locale)}</span>
            )}
            {job.status === "succeeded" ? (
              <CheckCircle2 size={12} className="text-success" />
            ) : job.status === "failed" ? (
              <CircleAlert size={12} className="text-destructive" />
            ) : job.progress > 0 ? (
              `${Math.round(job.progress * 100)}%`
            ) : (
              // 一次没报过进度就**别报数**。视频生成这类活儿,供应商只在做完时回一次结果,
              // 中间没有百分比可言 —— 而一个挂了五分钟的「0%」读起来就是"卡死了"
              // (真机反馈原话:一直挂在这个状态上没动)。这时有用的是**已经跑了多久**。
              <span title={job.created_at}>{t("jobRunningFor").replace("{t}", relativeTime(job.created_at, locale))}</span>
            )}
            {running && onCancel && (
              <button
                type="button"
                className="ml-[3px] inline-grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-destructive"
                title={t("jobCancel")}
                aria-label={t("jobCancel")}
                onClick={(event) => {
                  event.stopPropagation();
                  onCancel();
                }}
              >
                <X size={11} />
              </button>
            )}
          </span>
        </div>
        {running && job.progress > 0 && <Progress value={Math.round(job.progress * 100)} />}
        <small className={cn("truncate text-ui-xs text-muted-foreground", failed && "text-destructive")} title={job.error ?? job.message}>
          {job.status === "failed" ? (job.error ?? job.message) : job.message}
        </small>
      </div>
    </div>
  );
}
