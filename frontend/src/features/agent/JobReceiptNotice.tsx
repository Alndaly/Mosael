import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, ListChecks, RotateCcw } from "lucide-react";

import { getJob, type JobSummary } from "@/api/client";
import { listGenerationJobs, retrieveGeneration } from "@/api/domains/generation";
import { useI18n } from "@/app/preferences";
import { FailureCard, failureFields, type FailureFix } from "@/components/failure/FailureCard";
import { JobDetailDialog } from "@/components/jobs/JobDetailDialog";
import { JobKindIcon, gotoJobPage, jobPage, useJobKinds } from "@/components/jobs/jobKinds";
import { jobSubjectText } from "@/components/jobs/SessionJobsCard";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { leaveNativeView } from "@/lib/nativeView";
import { cn } from "@/lib/utils";

/** 后台任务回执那条消息的形状(后端 host.JOB_RECEIPT_ROLE)。 */
export const JOB_RECEIPT_ROLE = "job_receipt";

/**
 * 回执的结构化事实(后端 receipts.receipt_payload 落库;出口再补 error_summary / error_detail / error_hint,
 * 按请求方的语言)。界面不读 content 那句 —— 那是给模型读的短句,翻不动语言。
 */
type ReceiptPayload =
  | {
      job_id?: string;
      asset_ids?: string[];
      kind?: string;
      status?: string;
      subject?: string;
      /** 这次挂了几份素材(结构):subject 为空时,卡上用种类 + 份数说清「这是哪来的」。 */
      source_asset_count?: number;
      undelivered?: boolean;
      error_key?: string;
      error_params?: Record<string, unknown>;
      /** 没有文案 key 的第三方原话(我们翻不了)。带 key 的失败这里是空串。 */
      error?: string;
      /** 出口按当前语言翻好的那三样(见 api/schemas/agent.AgentMessageOut)。 */
      error_summary?: string | null;
      error_detail?: string | null;
      error_hint?: FailureFix | null;
      workspace_id?: string;
      generation_id?: string;
      generation_session_id?: string;
      project_id?: string;
    }
  | null
  | undefined;

/** 还没交给智能体的回执:这一轮结束时一并交出去,在那之前画在正在跑的那一轮下面。 */
export function isWaitingReceipt(message: { role: string; payload?: unknown }): boolean {
  return message.role === JOB_RECEIPT_ROLE && Boolean((message.payload as ReceiptPayload)?.undelivered);
}

/**
 * 后台任务跑完送回来的回执。
 *
 * **成功的不在对话里常驻** —— 右侧「后台任务」那块列着它(状态、进度、取消、结果都在那儿),对话里再留
 * 一行「已完成」是把同一件事说两遍。失败和被停下的仍然是一张卡:用户要在这里看见「哪个任务、为什么、
 * 下一步点哪儿」。
 *
 * 卡是全应用那一份失败展示(`FailureCard`)—— 此前这里是一行 muted 的中文正文,失败原因由后端
 * **落库时**渲染,英文界面里永远是中文;而且除了任务 id 之外没有任何可点的东西。现在 payload 带着种类、
 * 状态、失败 key 与参数、完整的 subject、生成记录 id,界面按当前语言重排。
 */
export function JobReceiptNotice({
  payload,
  className,
}: {
  /** 给模型读的那一句。卡上不读它 —— 失败原因走出口翻好的三样。 */
  content: string;
  payload: unknown;
  className?: string;
}) {
  const receipt = payload as ReceiptPayload;
  // 成功(以及老形状里没有 status 的)不渲染:交给右侧的任务列表。被停下的和失败的要一张卡。
  if (!receipt || (receipt.status !== "failed" && receipt.status !== "cancelled")) return null;
  return <ReceiptCard receipt={receipt} className={className} />;
}

function ReceiptCard({
  receipt,
  className,
}: {
  receipt: NonNullable<ReceiptPayload>;
  className?: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { kindOf } = useJobKinds();
  const kind = kindOf(receipt.kind ?? "");
  //: 用户写的那句;没写就按种类 + 素材份数拼一句(份数由后端结构化带出,见 receipts.receipt_payload)。
  const subject = jobSubjectText(receipt.subject, kind.label, t, receipt.source_asset_count ?? 0);
  const failed = receipt.status === "failed";
  const [detailJob, setDetailJob] = React.useState<JobSummary | null>(null);

  //: 任务详情现取(列表里那一行不在手上;回执只带 id)。点开之前不花这一次请求;
  //: 取不到(任务被清掉了)由全局的 mutation 兜底说一声,而不是点了一下什么都不发生。
  const openTask = useMutation({
    mutationFn: () => getJob(receipt.job_id!),
    onSuccess: (job) => setDetailJob(job),
  });

  //: 「重新取回」只在后端说 `retrievable` 时摆(远端已经做完、是我们没拿到):查这条生成记录要的那一页。
  const generations = useQuery({
    queryKey: ["generation", "receipt", receipt.generation_id],
    queryFn: () =>
      listGenerationJobs(receipt.workspace_id!, {
        sessionId: receipt.generation_session_id!,
        limit: 200,
      }),
    enabled:
      failed &&
      Boolean(receipt.generation_id) &&
      Boolean(receipt.generation_session_id) &&
      Boolean(receipt.workspace_id),
    staleTime: 15_000,
    retry: false,
  });
  const generation = generations.data?.find((one) => one.id === receipt.generation_id);
  const retrieve = useMutation({
    mutationFn: () => retrieveGeneration(receipt.generation_id!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["generation"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  //: 「前往」去的是这条任务的结果页:生成类落到那条创作记录,其余按任务目录声明的页面。
  const target = {
    payload: {
      ...(receipt.project_id ? { project_id: receipt.project_id } : {}),
      ...(receipt.generation_session_id ? { session_id: receipt.generation_session_id } : {}),
    },
  };
  const page = jobPage(target, kind);
  const gotoLabel = receipt.generation_id ? t("chatJobsGotoGeneration") : t("chatJobsGoto");
  const gotoResult = () => {
    void leaveNativeView();
    gotoJobPage(target, kind);
  };

  const actions = (
    <>
      <Button
        variant="outline"
        size="xs"
        loading={openTask.isPending}
        onClick={() => openTask.mutate()}
        data-receipt-open-task=""
      >
        <ListChecks size={13} />
        {t("chatJobsOpenTask")}
      </Button>
      {page ? (
        <Button variant="outline" size="xs" onClick={gotoResult} data-receipt-goto="">
          <ExternalLink size={13} />
          {gotoLabel}
        </Button>
      ) : null}
      {/* 「重新取回」只在后端说 retrievable 时摆:远端已经做完、是我们没拿到结果,再去取一次 ——
          不重新提交,不会再付一次钱(生成页那张失败卡上的同一档动作,同一个接口)。 */}
      {generation?.retrievable ? (
        <Hint label={t("genRetrieveHint")}>
          <Button
            variant="outline"
            size="xs"
            loading={retrieve.isPending}
            onClick={() => retrieve.mutate()}
            data-receipt-retrieve=""
          >
            <RotateCcw size={12} />
            {t("chatReceiptRetrieve")}
          </Button>
        </Hint>
      ) : null}
    </>
  );

  const meta = (
    <span className="flex min-w-0 max-w-[320px] items-center gap-1.5 text-ui-xs text-muted-foreground">
      <JobKindIcon meta={kind} size={12} />
      <span className="shrink-0">{kind.label}</span>
      {subject ? (
        <>
          <span className="shrink-0" aria-hidden>·</span>
          <Truncate className="flex-1">{subject}</Truncate>
        </>
      ) : null}
    </span>
  );

  const waiting = receipt.undelivered ? (
    <p className="m-0 text-ui-2xs text-muted-foreground">{t("chatReceiptWaiting")}</p>
  ) : null;

  const dialog = (
    <JobDetailDialog
      job={detailJob}
      onClose={() => setDetailJob(null)}
      onGoto={
        page
          ? () => {
              gotoResult();
              setDetailJob(null);
            }
          : undefined
      }
      gotoLabel={gotoLabel}
    />
  );

  if (receipt.status === "cancelled") {
    return (
      <div className={cn("min-w-0", className)} data-job-receipt="" data-receipt-cancelled={receipt.job_id}>
        <FailureCard
          status="stopped"
          title={t("genStopped")}
          summary={t("genStoppedBody")}
          meta={meta}
          actions={actions}
          className="w-[min(560px,100%)]"
        >
          {waiting}
        </FailureCard>
        {dialog}
      </div>
    );
  }

  const fields = failureFields(
    { error: receipt.error, error_summary: receipt.error_summary, error_detail: receipt.error_detail, error_hint: receipt.error_hint },
    t("genFailed"),
  );
  return (
    <div className={cn("min-w-0", className)} data-job-receipt="" data-receipt-failed={receipt.job_id}>
      <FailureCard
        title={t("failureOfKind").replace("{kind}", kind.label)}
        summary={fields.summary}
        detail={fields.detail}
        fix={fields.fix}
        copyText={fields.copyText}
        meta={meta}
        actions={actions}
        className="w-[min(560px,100%)]"
      >
        {waiting}
      </FailureCard>
      {dialog}
    </div>
  );
}
