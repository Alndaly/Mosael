import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Loader2 } from "lucide-react";

import { cancelJob, topLevelJobsQuery, type JobSummary } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { InspectorCard } from "@/components/layout/InspectorCard";
import { InspectorStatusRow, toAgentStatus } from "@/components/layout/InspectorStatusRow";
import { JobDetailDialog } from "@/components/jobs/JobDetailDialog";
import { gotoJobPage, jobPage, useJobKinds } from "@/components/jobs/jobKinds";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { leaveNativeView } from "@/lib/nativeView";
import { formatElapsedSeconds } from "@/lib/time";

const ACTIVE = new Set(["queued", "running"]);

/** 任务载荷里「这份回执寄回哪次对话」那一块(见后端 receipts.receipt_to_session)。 */
function receiptSessionId(job: JobSummary): string | null {
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const receipt = payload.receipt as { session_id?: unknown } | undefined;
  return typeof receipt?.session_id === "string" ? receipt.session_id : null;
}

/**
 * 任务名字的公共规则 —— 「本对话的后台任务」「任务中心」「回执卡」三处**同一份**,不各写一版。
 *
 * 后端把 `payload.subject` 收窄成「只放用户自己写的那句」,没写就是**空串**(不再塞喂给模型的整段
 * 正文,也不塞模型名)。空的时候由展示层自己说清「这是哪来的」:按**当前语言** + **任务种类**
 * (useJobKinds 的种类名)+ **素材份数**拼一句;没有份数就只说种类(种类名本来就在行上,不重复)。
 *
 * 有内容时**原样**给出:旧任务的 `subject` 可能是整篇,`request.prompt` 一直是完整提示词 ——
 * 放不下由调用方的 `Truncate` 收,不在这里切。
 */
export type JobSubjectTranslator = (key: MessageKey) => string;

/** 这次请求挂了几份素材(生成把它们记在 `request.source_assets` 上)。 */
export function sourceAssetCount(payload: unknown): number {
  const request = (payload as { request?: { source_assets?: unknown } } | null | undefined)?.request;
  const assets = request?.source_assets;
  return Array.isArray(assets) ? assets.length : 0;
}

/**
 * 一个任务的标题。`written` 是用户自己写的那句;空的时候用种类 + 素材份数拼一句。
 *
 * @param count 这次挂了几份素材(回执卡从 `source_asset_count` 拿,列表从 `request.source_assets` 数)。
 */
export function jobSubjectText(
  written: unknown,
  kindLabel: string,
  t: JobSubjectTranslator,
  count: number,
): string | null {
  const text = typeof written === "string" ? written.trim() : "";
  if (text) return text;
  //: 目录还没到时种类名是空的:宁可晚一拍(目录到了会重渲),也不先说半句「从 2 个素材 」。
  if (count > 0 && kindLabel) {
    return t("jobSubjectFromAssets").replace("{count}", String(count)).replace("{kind}", kindLabel);
  }
  //: 没有份数:种类名已经单独显示在行上 —— 返回 null,别把「AI 生成」再说一遍。
  return null;
}

/** `jobSubjectText` 的任务载荷版:先读用户那句(`request.prompt` 是旧任务也能拿到的原文),再读 subject。 */
export function jobSubjectOf(
  job: Pick<JobSummary, "payload">,
  kindLabel: string,
  t: JobSubjectTranslator,
): string | null {
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const request = payload.request as { prompt?: unknown } | undefined;
  const prompt = typeof request?.prompt === "string" ? request.prompt.trim() : "";
  const subject = payload.subject;
  const written = prompt || (typeof subject === "string" ? subject.trim() : "");
  return jobSubjectText(written, kindLabel, t, sourceAssetCount(payload));
}

/**
 * 右侧「本对话的后台任务」:这次对话发起的那些任务行 —— 跨轮次、跨重启,有进度、能取消、看得到结果。
 *
 * 它和下面的「最近工具」是两件事:那边是**每一次工具调用**(读一次文件、开一次浏览器都算,只留 6 条),
 * 这边是**任务行**(提交之后在后台跑、隔了几轮才结束的东西)。合成一块会把"它到底提交了什么"和
 * "它刚才读了什么"混成一列,两种东西的寿命和可操作性都不一样。
 *
 * 数据复用任务中心那份 `/api/jobs` 查询,在前端按 `payload.receipt.session_id` 过滤 —— 不为一个面板
 * 给接口加开关参数。轮询间隔也照任务中心:有在跑的 1.5 秒,没有的 8 秒。
 */
export function SessionJobsCard({ workspaceId, sessionId }: { workspaceId: string; sessionId: string | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { kindOf } = useJobKinds();
  const [detailJob, setDetailJob] = React.useState<JobSummary | null>(null);

  const jobsQuery = React.useMemo(() => topLevelJobsQuery(workspaceId), [workspaceId]);
  const jobs = useQuery({
    ...jobsQuery,
    enabled: Boolean(sessionId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 1500 : 8000,
  });

  const mine = React.useMemo(() => {
    // 先看在跑的,再看排队的,最后是已经结束的;同一档里新的在上。侧栏只扫一眼,
    // 「现在有什么在跑」必须第一眼看见,而不是被上一条做完的任务顶下去。
    const rank = (status: string) =>
      status === "running" ? 0 : status === "queued" ? 1 : status === "failed" ? 2 : 3;
    return (jobs.data ?? [])
      .filter((job) => receiptSessionId(job) === sessionId)
      .sort((a, b) => rank(a.status) - rank(b.status) || Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [jobs.data, sessionId]);

  const cancel = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  });

  if (!sessionId || mine.length === 0) return null;

  const detailKind = detailJob ? kindOf(detailJob.kind) : null;
  const detailPage = detailJob && detailKind ? jobPage(detailJob, detailKind) : null;

  return (
    <InspectorCard icon={ListChecks} title={t("chatJobsTitle")} aside={String(mine.length)}>
      <div className="grid min-w-0 gap-2" data-session-jobs="">
        <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("chatJobsScope")}</p>
        <ul className="m-0 grid list-none gap-1.5 p-0">
        {mine.map((job) => {
          const kind = kindOf(job.kind);
          const subject = jobSubjectOf(job, kind.label, t);
          const active = ACTIVE.has(job.status);
          const failed = job.status === "failed";
          const page = jobPage(job, kind);
          const progress = typeof job.progress === "number" ? job.progress : 0;
          const elapsed = Math.max(0, (Date.now() - Date.parse(job.created_at)) / 1000);
          const meta = active
            ? progress > 0
              ? `${Math.round(progress * 100)}%`
              : t("chatJobsElapsed").replace("{t}", formatElapsedSeconds(elapsed))
            : failed && (job.error_summary || job.error)
              ? job.error_summary || job.error
              : null;
          return (
            <li key={job.id} data-session-job={job.id}>
              {/* 和「任务计划」同一个 InspectorStatusRow:左边一个圈、右边文字,右侧不再写一遍状态。
                  主行只放用户写的题目(没有题目时才用种类名当主行);种类、进度/用时/失败原因都归
                  说明行,和文字同一左缘。题目本身是一颗悬停才出现下划线的文字按钮,点它看详情。 */}
              <InspectorStatusRow
                status={toAgentStatus(job.status)}
                note={
                  subject ? (
                    <span className="flex min-w-0 items-baseline gap-1.5">
                      <span className="shrink-0">{kind.label}</span>
                      {meta ? <Truncate className="flex-1 tabular-nums">{meta}</Truncate> : null}
                    </span>
                  ) : meta ? (
                    <Truncate className={active ? "tabular-nums" : undefined}>{meta}</Truncate>
                  ) : null
                }
                noteTrailing={
                  active ? (
                    <button
                      type="button"
                      className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-ui-2xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline disabled:pointer-events-none disabled:opacity-50"
                      disabled={cancel.isPending && cancel.variables === job.id}
                      onClick={() => cancel.mutate(job.id)}
                    >
                      {cancel.isPending && cancel.variables === job.id ? (
                        <Loader2 className="size-3 animate-mosael-spin" aria-label={t("jobCancel")} />
                      ) : (
                        t("jobCancel")
                      )}
                    </button>
                  ) : failed && page ? (
                    <button
                      type="button"
                      className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-ui-2xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
                      onClick={() => {
                        void leaveNativeView();
                        gotoJobPage(job, kind);
                      }}
                    >
                      {t("chatJobsGoto")}
                    </button>
                  ) : null
                }
              >
                <Button
                  variant="inline"
                  className="-ml-1.5 w-full min-w-0 justify-start font-normal text-foreground hover:bg-transparent hover:text-foreground hover:underline"
                  onClick={() => setDetailJob(job)}
                >
                  <Truncate>{subject || kind.label}</Truncate>
                </Button>
              </InspectorStatusRow>
            </li>
          );
        })}
        </ul>
      </div>
      <JobDetailDialog
        job={detailJob}
        onClose={() => setDetailJob(null)}
        onGoto={
          detailJob && detailPage
            ? () => {
                void leaveNativeView();
                if (detailJob) gotoJobPage(detailJob, kindOf(detailJob.kind));
                setDetailJob(null);
              }
            : undefined
        }
        gotoLabel={detailJob?.status === "failed" && detailJob.kind === "ai_generation" ? t("chatJobsGotoGeneration") : undefined}
      />
    </InspectorCard>
  );
}
