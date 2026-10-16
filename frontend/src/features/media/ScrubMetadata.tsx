import * as React from "react";
import { QueryClientContext, useQuery } from "@tanstack/react-query";
import { Eraser, FileText, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import {
  getJob,
  getScrubReport,
  listJobs,
  SCRUB_JOB_KIND,
  startScrub,
  type Asset,
  type JobSummary,
  type ScrubGate,
  type ScrubOutcome,
  type ScrubReport,
} from "@/api/client";
//: 这一条**从它自己的模块**读,不走 `@/api/client` 那个桶:有几个画板用例把整个桶换成一张局部替身,
//: 读一个它没列出的导出会在**取值那一刻**就抛(vitest 的替身如此),连 `typeof x === "function"` 都来不及判。
//: 而这一块是素材详情里的一个附加动作,不该让那些用例整棵树挂掉。
import { scrubOutcomeOf } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import { scrubKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
import { jobSettled } from "@/components/jobs/runStatus";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

/**
 * 清除元数据(ADR 0062)在素材详情里的入口与出口。**只做视频**。
 *
 * 维护者拍板的那一种入口:「素材详情页一个动作」,不是"保存时勾选"。所以形状是一颗按钮 →
 * 一张小确认面板(`provenance` 开关 + 后果原文 + 「原素材不动,会多出一份干净素材」)→ 任务 →
 * 出口(打开新素材 / 看对账 /「来自」写 `scrub`)。
 *
 * 状态只有一份,**由素材详情拿着**([`useScrubRun`]):头部那颗按钮和右栏那一块读的是**同一条任务**
 * (两处各拉一次列表,两边会在轮询之间看到不同的进度)。这两块都是"给什么画什么"的,自己不取数 ——
 * 面板只在视频上挂(见 AssetPreviewModal)。
 *
 * 不自己造轮询:任务列表走 `listJobs(kind=scrub_metadata)`,和「拆镜头」同一套写法 —— 有任务在跑时
 * 1.5 秒问一次,结束了就不再问;那条任务在**任务中心**里看进度、取消(任务中心自己就在轮询 `/api/jobs`)。
 */

/** 这条视频的清除任务、结果、以及对账 —— 详情页那一层拿到的全部。 */
export type ScrubRun = {
  /** 结果那一份任务详情(读不到就是 null)。 */
  run: JobSummary | null;
  /** 结果里那一份:新素材 id、对账、十道门、清掉了什么。 */
  outcome: ScrubOutcome | null;
  /** 还在跑的那一条(界面据此显示「进行中」)。 */
  active: JobSummary | null;
  /** 跑完过没有(哪怕这个弹窗是后开的)。 */
  done: boolean;
  /** 最近一次**没成**的那条(有的话):它的那一句原因要给人看,不然点完一次之后这里什么都没了。 */
  failed: JobSummary | null;
  report: ScrubReport | undefined;
  reportPending: boolean;
  /**
   * 刚排上那一条。它不属于「这条视频的当前结果」,但界面要在任务列表回来之前就说得出「在做」。
   */
  startedJobId: string | null;
  /** 排一条清除任务(确认面板那颗按钮就是它)。 */
  start: {
    /** 开这一趟(确认面板按的是它);`onQueued` 是排上之后那一串(提示、开任务中心、收起面板)。 */
    queue: (provenance: boolean, onQueued?: (job: JobSummary) => void) => void;
    /** 还在排(那颗按钮转圈)。 */
    pending: boolean;
    /** 没排上(确认面板里那张失败卡)。 */
    error: unknown;
  };
};

/**
 * 这条视频的清除任务:还在跑的那条、最近跑完的那条、结果,以及对账文本。
 *
 * 任务列表按种类问(`listJobs(kind=scrub_metadata)`):**状态不在组件里** —— 弹窗关掉再打开,
 * 「进行中」和跑完的出口照旧在。
 */
export function useScrubRun(asset: Asset | null): ScrubRun {
  /**
   * 没有查询上下文时(某些只摆一个弹窗、不套 QueryClientProvider 的测试)就当作"这条视频没有清除任务":
   * **这一块不该让整份素材详情挂掉** —— 它是详情里的一个附加动作,不是详情的前提。
   *
   * 直接读那个 context 而不是 `useQueryClient()`:后者在没有 Provider 时直接抛,而抛之前没有一个判断的余地。
   */
  const qc = React.useContext(QueryClientContext);
  //: 刚排上那一下:列表还没回来之前先把它当成「在做」,免得那一行闪一下又不见。
  const [started, setStarted] = React.useState<string | null>(null);
  //: 还没有素材(那一格是空的)时只有这一个键:`asset` 在下面每一处都当非空用。
  const assetId = asset?.id ?? "";
  const workspaceId = asset?.workspace_id ?? "";

  const jobs = useQuery({
    queryKey: scrubKeys.pending(workspaceId),
    queryFn: () => listJobs(workspaceId, { kind: SCRUB_JOB_KIND }),
    //: 没有素材、或者没有查询上下文(只摆一个弹窗的测试)时就**不问** —— `useQuery` 本身也会去读 context。
    enabled: Boolean(asset) && Boolean(qc),
    refetchInterval: (query) => (runningIn(query.state.data, assetId) ? 1500 : false),
  });

  const mine = (jobs.data ?? []).filter((row) => row.payload?.asset_id === assetId);
  const active = mine.find((row) => !jobSettled(row.status)) ?? null;
  const done = mine.find((row) => row.status === "succeeded") ?? null;
  const failed = mine.find((row) => row.status === "failed") ?? null;
  //: 结果只在**任务详情**里给(`/api/jobs` 那一列不带 `result`),所以按 id 现取那一条。
  const jobId = done?.id ?? started;
  const detail = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
  });
  /** 结果那一份。不是这个形状(别的任务、老数据、没结果的替身)时是 `null`,不猜。 */
  const outcome = React.useMemo(() => scrubOutcomeOf(detail.data?.result), [detail.data]);
  const cleanId = outcome?.asset_id ?? "";

  /**
   * 对账文本。**先在干净素材上问、再在源素材上问**:后端把对账写在源文件旁边(`<stem>.scrub-report.md`),
   * 而干净素材的文件名带着它自己的后缀 —— 哪一边读得到由后端说了算,这里两个 id 各问一次、拿到 `ready` 的
   * 那一份就用它。
   *
   * 没清过是 200 + `status: "none"`(不是 404),所以两个 id 都能放心问。
   */
  const cleanReport = useQuery({
    queryKey: scrubKeys.report(cleanId),
    queryFn: () => getScrubReport(cleanId),
    enabled: Boolean(cleanId) && Boolean(qc),
  });
  const sourceReport = useQuery({
    queryKey: scrubKeys.report(assetId),
    queryFn: () => getScrubReport(assetId),
    //: 干净素材那一份就够时不再问源素材;它答 `none`(或者还没跑过)时才补问一次。
    enabled: Boolean(done) && Boolean(assetId) && Boolean(qc) && cleanReport.isSuccess && cleanReport.data.status !== "ready",
  });
  const report: ScrubReport | undefined =
    cleanReport.data?.status === "ready" ? cleanReport.data : sourceReport.data;

  //: 那条任务在列表里出现了就不再靠「刚排上」顶着(不然轮询之间会来回闪)。
  React.useEffect(() => {
    if (started && mine.some((row) => row.id === started)) setStarted(null);
  }, [started, mine]);

  /**
   * 排一条清除任务。**发请求的按钮在确认面板里**(它有自己的 `loading`),这一趟住在这里:
   * 「排上一条」要同时更新确认面板那颗按钮、右栏那一行进行中、以及任务中心那份缓存。
   *
   * 用手写的三格状态而不是 `useMutation`:后者要在渲染时就拿到查询上下文,而这一块在"只摆一个弹窗、
   * 没有 Provider"的地方(画板的几种用例)也得能渲染出来 —— 它的失败只该是"排不上",不该是整份详情挂掉。
   * 成不成、失败原文都在下面,`onQueued` 交给确认面板(它要弹 toast、要开任务中心、要收起自己)。
   */
  const [pending, setPending] = React.useState(false);
  const [failure, setFailure] = React.useState<unknown>(null);
  const queue = React.useCallback((provenance: boolean, onQueued?: (job: JobSummary) => void) => {
    setPending(true);
    setFailure(null);
    startScrub(assetId, provenance).then(
      (job) => {
        setStarted(job.id);
        setPending(false);
        void qc?.invalidateQueries({ queryKey: scrubKeys.pending(workspaceId) });
        void qc?.invalidateQueries({ queryKey: ["jobs", workspaceId] });
        onQueued?.(job);
      },
      (error: unknown) => {
        setPending(false);
        setFailure(error);
      },
    );
  }, [assetId, workspaceId, qc]);

  return {
    run: detail.data ?? null,
    outcome,
    active,
    done: Boolean(done),
    failed,
    report,
    //: **`isPending` 不是"正在取"**:一个还没打开过、也没数据的查询,状态也是 `pending`(见 React Query 的
    //: status 定义)。这里要问的是"对账这一份是不是还在路上",那是 `isFetching`。
    reportPending: cleanReport.isFetching || sourceReport.isFetching,
    startedJobId: started,
    start: { queue, pending, error: failure },
  };
}

/** 这条视频还在清的那条任务;没有就是 null。 */
function runningIn(rows: JobSummary[] | undefined, assetId: string): JobSummary | null {
  return (rows ?? []).find((row) => row.payload?.asset_id === assetId && !jobSettled(row.status)) ?? null;
}

/**
 * 头部那一颗「清除元数据…」:点开确认面板。**只给视频** —— 后端只收视频(`scrubErr_notVideo`)。
 *
 * 摆在「保存到本地」旁边(见 AssetPreviewModal 的 headerActions):那是这份素材上"把它交出去"的
 * 两个动作,位置也该挨着。
 */
export function ScrubActionButton({ asset, run, open, onOpenChange }: {
  asset: Asset;
  run: ScrubRun;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useI18n();
  if (asset.kind !== "video") return null;
  return (
    <>
      <Button variant="outline" size="xs" data-scrub-action="" onClick={() => onOpenChange(true)}>
        <Eraser />
        {t("scrubAction")}
      </Button>
      {open && <ScrubConfirmDialog run={run} onClose={() => onOpenChange(false)} />}
    </>
  );
}

/**
 * 确认面板。**不是一句确认**:里面是那个开关、它的后果原文,以及「原素材不动」这句话。
 *
 * 文案取的是后端 `domain/assets/scrub/policy.PROVENANCE` 那一句(`consequence_zh` / `consequence_en`),
 * 中英各一份放在文案表里(`scrubProvenanceConsequence`)—— 素材详情读不到那个 Python 常量,同一句话
 * 抄一份是本仓库的既有做法(节点文案、确认卡、对账文本已经各引一次)。
 */
function ScrubConfirmDialog({ run, onClose }: { run: ScrubRun; onClose: () => void }) {
  const t = useI18n();
  //: **默认关** —— 和后端 `policy.PROVENANCE["default"]` 一致,不打架。
  const [provenance, setProvenance] = React.useState(false);
  const start = run.start;
  const queue = () => {
    start.queue(provenance, (job) => {
      toast.success(t("scrubStarted"));
      //: 进度和取消在任务中心(既有那一套)。点一下就把它打开。
      if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("mosael:open-tasks", { detail: job.id }));
      onClose();
    });
  };

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onClose()}
      title={t("scrubTitle")}
      className="sm:max-w-lg"
      footer={
        <>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" loading={start.pending} onClick={queue}>
            {t("scrubStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5" data-scrub-confirm="">
        {/* 清的是什么:四类逐条点名,不堆成一句"元数据"。 */}
        <p className="m-0 text-ui-xs leading-[1.6] text-muted-foreground">{t("scrubHint")}</p>
        {/* 「原素材不动」:这是用户按下之前唯一需要知道的结果。 */}
        <p className="m-0 text-ui-sm leading-[1.6] text-foreground">{t("scrubSourceUntouched")}</p>

        <div className="grid gap-2 rounded-lg border border-border p-3.5">
          <label className="flex cursor-pointer items-start gap-3" htmlFor="scrub-provenance">
            <Switch
              id="scrub-provenance"
              className="mt-0.5"
              checked={provenance}
              onCheckedChange={setProvenance}
              aria-label={t("scrubProvenanceLabel")}
            />
            <span className="grid min-w-0 gap-1">
              <span className="text-ui-sm font-medium leading-5 text-foreground">{t("scrubProvenanceLabel")}</span>
              <span className="text-ui-xs leading-[1.6] text-muted-foreground">{t("scrubProvenanceOff")}</span>
            </span>
          </label>
          {/* 后果原文:打开时整幅给它;关着时也照旧可读(那段话说清了"关掉时这些标记原样保留")。 */}
          <p
            data-scrub-consequence=""
            className={cn(
              "m-0 border-l-2 border-warning pl-3 text-ui-xs leading-[1.6]",
              provenance ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {t("scrubProvenanceConsequence")}
          </p>
        </div>

        {start.error != null && (
          //: 失败展示走全应用那一份卡(FailureCard):原文、原因、复制都在里头,不手写一行红字。
          <FailureCard
            status="failed"
            size="compact"
            align="start"
            title={t("scrubStartFailed")}
            {...rawFailureFields(errorText(start.error), t("scrubStartFailed"))}
          />
        )}
      </div>
    </ModalShell>
  );
}

/**
 * 右栏那一块。三件事:
 *
 * - **在跑**:一行进行中(进度和取消在任务中心);
 * - **跑完的出口**:「打开这份干净素材」(跳到新素材的详情)和「查看对账」(把那份 Markdown 摊开);
 * - **如实**:十道门逐条、`removed` 按中文说清、`warnings` 逐条。
 *
 * 这条视频**还没清过**时整块不出现 —— 入口在头部那一颗按钮上。
 */
export function ScrubMetadataPanel({
  asset,
  run,
  onOpenAsset,
}: {
  asset: Asset;
  run: ScrubRun;
  /** 「打开这份干净素材」:跳到那一份的详情(和新素材的「来自」互相指得回来)。 */
  onOpenAsset: (assetId: string) => void;
}) {
  const t = useI18n();
  const [reportOpen, setReportOpen] = React.useState(false);
  if (asset.kind !== "video") return null;
  //: 还没清过、没有刚排上的、也没失败过时整块不出现 —— 入口在头部那一颗按钮上。
  if (!run.active && !run.done && !run.startedJobId && !run.failed) return null;

  const outcome = run.outcome;
  const failed = outcome?.gates.filter((gate) => !gate.ok).length ?? 0;
  //: 在跑:列表里那条,或者刚排上、列表还没回来的那一条。
  const running = run.active ?? (!run.done && run.startedJobId ? ({ id: run.startedJobId } as JobSummary) : null);
  return (
    <section data-scrub-panel="" className="grid gap-2 border-t border-divider pt-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-ui-xs font-medium text-muted-foreground">{t("scrubTitle")}</h3>
        {/* 门禁那一眼的结论:全过是「过」,没敢交是「没过几道」—— 一个词,不抢上面那一行。 */}
        {outcome && failed > 0 && (
          <span data-scrub-gate-badge="" className="text-ui-2xs tabular-nums text-warning">
            {`${failed}/${outcome.gates.length}`}
          </span>
        )}
      </div>

      {running && (
        <p role="status" data-scrub-running="" className="m-0 flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          <Loader2 size={12} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />
          {running.message?.trim() || t("scrubRunning")}
        </p>
      )}

      {!running && outcome && (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="xs" variant="outline" data-scrub-open="" onClick={() => onOpenAsset(outcome.asset_id)}>
              <Eraser />
              {t("scrubOpening")}
            </Button>
            <Button size="xs" variant="outline" data-scrub-report="" onClick={() => setReportOpen(true)}>
              <FileText />
              {t("scrubOpenReport")}
            </Button>
          </div>
          <GatesList gates={outcome.gates} gatesOk={outcome.gates_ok} />
          <RemovedList removed={outcome.removed} />
          {(outcome.warnings?.length ?? 0) > 0 && (
            <div className="grid gap-1">
              <span className="text-ui-2xs font-medium text-muted-foreground">{t("scrubWarningsTitle")}</span>
              <ul className="m-0 grid list-none gap-0.5 p-0">
                {outcome.warnings?.map((note) => (
                  <li key={note} data-scrub-warning="" className="text-ui-2xs leading-4 text-muted-foreground">
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* 上一次没成:**说出来**,不然点完一次之后这一块就空了 —— 失败的样子走全应用那一份卡。 */}
      {!running && !outcome && run.failed && (
        <FailureCard
          status="failed"
          size="compact"
          align="start"
          data-scrub-failed=""
          title={t("scrubStartFailed")}
          summary={run.failed.error_summary?.trim() || errorText(run.failed.error)}
        />
      )}

      {/* 任务成了、结果还没读回来(或者老数据里没有 `result`):说清"在看哪一条",不留一块空白。 */}
      {!running && !outcome && run.done && (
        <p data-scrub-result-pending="" className="m-0 flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          <Loader2 size={12} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />
          {t("scrubRunning")}
        </p>
      )}

      {reportOpen && <ScrubReportDialog report={run.report} pending={run.reportPending} onClose={() => setReportOpen(false)} />}
    </section>
  );
}

/** 硬门:红了说明产出不可信,引擎不许交出去(后端 `gates.HARD_GATES`)。 */
const HARD_GATES = new Set(["G6", "G7", "G9"]);

/** 十道门逐条:过 / 没过 + 那一句说明。硬门单独标出来。 */
function GatesList({ gates, gatesOk }: { gates: ScrubGate[]; gatesOk: boolean }) {
  const t = useI18n();
  const hardFailed = gates.some((gate) => !gate.ok && HARD_GATES.has(gate.id));
  return (
    <div className="grid gap-1.5" data-scrub-gates="">
      <div className="grid gap-1">
        <span className="text-ui-2xs font-medium text-muted-foreground">
          {t("scrubGateTitle").replace("{n}", String(gates.length))}
        </span>
        {/* 结论一句话:全过是一种说法,没敢交是另一种 —— 后者要显眼,但不吓人(它只是"没敢说都干净")。 */}
        <span className={cn("text-ui-2xs leading-4", gatesOk ? "text-muted-foreground" : "text-warning")}>
          {gatesOk ? t("scrubGateAllPassed") : hardFailed ? t("scrubGateHardFailed") : t("scrubGateSoftFailed")}
        </span>
      </div>
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {gates.map((gate) => (
          <li key={gate.id} data-scrub-gate={gate.id} data-ok={gate.ok ? "" : undefined} className="flex min-w-0 items-start gap-1.5">
            {gate.ok ? (
              <ShieldCheck size={12} className="mt-0.5 shrink-0 text-success" aria-hidden />
            ) : (
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-warning" aria-hidden />
            )}
            <span className="min-w-0 text-ui-2xs leading-4 text-muted-foreground">
              <span className="font-mono tabular-nums text-foreground">{gate.id}</span>{" "}
              <span>{gate.name}</span>{" "}
              <span className={gate.ok ? "text-muted-foreground" : "text-warning"}>
                {gate.ok ? t("scrubGateOk") : t("scrubGateFailed")}
              </span>
              {HARD_GATES.has(gate.id) && (
                <span className="ml-1 rounded-sm bg-secondary px-1 text-ui-2xs">{t("scrubGateHard")}</span>
              )}
              {gate.detail ? <span className="block text-muted-foreground">{gate.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 清掉了什么。**按中文说清每一项**,不摊一串英文键。
 *
 * 只列大于 0 的(「清了 0 条」不是清账,是噪音),一个都没有时说「没有可清的」—— 后端新加了一种计数,
 * 这里认得就翻成人话、不认得就原样列在最后,不显示成 0、也不悄悄吞掉。
 */
const REMOVED_LABELS: Array<[string, MessageKey]> = [
  ["sei_nals", "scrubRemoved_sei_nals"],
  ["sei_payloads", "scrubRemoved_sei_payloads"],
  ["aac_dse", "scrubRemoved_aac_dse"],
  ["aac_dse_zeroed", "scrubRemoved_aac_dse_zeroed"],
  ["aac_fill_zeroed", "scrubRemoved_aac_fill_zeroed"],
  ["compressorname", "scrubRemoved_compressorname"],
  ["uuid_boxes", "scrubRemoved_uuid_boxes"],
  ["data_tracks", "scrubRemoved_data_tracks"],
  ["container_keys", "scrubRemoved_container_keys"],
  ["provenance_kept", "scrubRemoved_provenance_kept"],
  ["provenance_removed", "scrubRemoved_provenance_removed"],
];

function RemovedList({ removed }: { removed: Record<string, number | undefined> }) {
  const t = useI18n();
  const known = new Set(REMOVED_LABELS.map(([key]) => key));
  const rows = REMOVED_LABELS.filter(([key]) => Number(removed[key]) > 0).map(([key, label]) => ({
    key,
    text: t(label).replace("{n}", String(Number(removed[key]))),
  }));
  const rest = Object.entries(removed)
    .filter(([key, value]) => !known.has(key) && Number(value) > 0)
    .map(([key, value]) => ({ key, text: `${key}: ${value}` }));
  const all = [...rows, ...rest];
  return (
    <div className="grid gap-1" data-scrub-removed="">
      <span className="text-ui-2xs font-medium text-muted-foreground">{t("scrubRemovedTitle")}</span>
      {all.length === 0 ? (
        <p className="m-0 text-ui-2xs leading-4 text-muted-foreground">{t("scrubRemovedNone")}</p>
      ) : (
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {all.map((row) => (
            <li key={row.key} data-scrub-removed-row={row.key} className="text-ui-2xs leading-4 text-muted-foreground">
              {row.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 对账文本:仓库既有的「看一段 Markdown」那一套(`AgentMarkdown`),不另造渲染器。 */
function ScrubReportDialog({
  report,
  pending,
  onClose,
}: {
  report: ScrubReport | undefined;
  pending: boolean;
  onClose: () => void;
}) {
  const t = useI18n();
  const markdown = report?.status === "ready" ? report.markdown : "";
  return (
    <ModalShell open onOpenChange={(next) => !next && onClose()} title={t("scrubReportTitle")} className="sm:max-w-2xl">
      <div data-scrub-report-body="" className="min-w-0 text-ui-sm">
        {pending ? (
          //: 对账还没读回来(任务刚做完那一下):转圈,不留一块空白。
          <p className="m-0 flex items-center gap-1.5 text-ui-xs text-muted-foreground">
            <Loader2 size={12} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />
            {t("scrubRunning")}
          </p>
        ) : markdown ? (
          <AgentMarkdown fullTables>{markdown}</AgentMarkdown>
        ) : (
          //: 没清过是 200 + `status: "none"`(不是 404):这里说人话,不报错、也不留一块空白。
          <p className="m-0 text-ui-xs text-muted-foreground">{t("scrubReportNone")}</p>
        )}
      </div>
    </ModalShell>
  );
}
