/**
 * 工作台面板里几处共用的小件。面板画在内嵌画布旁边那一列,原生网页视图盖在一切 DOM 上 —— 居中的弹窗会被画布盖住,
 * 所以要确认的事就地确认(`InlineConfirm`),不弹框。
 *
 * 版式的规矩(那一列每个页签都一样):说明、提醒、出错贴在顶上;**空的、在读的**摆在面板正中(`PanelEmpty` /
 * `PanelLoading`)。为此每个页签都是一个竖排的 flex(`ComfyWorkbench` 里那一层,自己滚动),面板的根也是竖排的
 * flex、占满剩下的高(`PANEL_ROOT`),空态和在读的那一块再占满剩下的、居中。
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";

import { getJob, type Job } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** 面板的根:竖排、占满页签剩下的高(空态、在读的才能摆在正中)。 */
export const PANEL_ROOT = "flex min-w-0 flex-1 flex-col";

/** 整块面板只有一句话(还没选节点、什么都不缺、还没跑过):一个图标 + 一句,摆在剩下那块的正中。 */
export function PanelEmpty({
  icon: Icon,
  tone = "muted",
  children,
}: {
  icon: LucideIcon;
  tone?: "muted" | "success";
  children: React.ReactNode;
}) {
  return (
    <div
      data-panel-state="empty"
      className={cn(
        "flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center text-ui-sm",
        tone === "success" ? "text-success" : "text-muted-foreground",
      )}
    >
      <Icon size={20} aria-hidden />
      <p className="m-0 max-w-[34ch] leading-relaxed">{children}</p>
    </div>
  );
}

/** 在读 / 在连:转圈摆在剩下那块的正中(LoadingState 在竖排的 flex 里用 `h-auto flex-1`,见它的说明)。 */
export function PanelLoading({ label }: { label: string }) {
  return <LoadingState label={label} className="h-auto min-h-0 flex-1" />;
}

/** 一句话:说明(status)、要注意(warning)、出错了(alert)。 */
export function PanelNote({
  tone = "info",
  children,
  action,
}: {
  tone?: "info" | "warning" | "error";
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  const Icon = tone === "error" ? CircleAlert : tone === "warning" ? TriangleAlert : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex min-w-0 items-start gap-2 rounded-lg border bg-panel p-2.5 text-ui-xs leading-relaxed text-foreground",
        tone === "error" ? "border-destructive/40" : tone === "warning" ? "border-warning/40" : "border-border",
      )}
    >
      <Icon
        size={13}
        aria-hidden
        className={cn("mt-0.5 shrink-0", tone === "error" ? "text-destructive" : tone === "warning" ? "text-warning" : "text-muted-foreground")}
      />
      <span className="min-w-0 flex-1 break-words">{children}</span>
      {action}
    </div>
  );
}

/** 就地确认:写明要改哪台机器上的什么,确认 / 取消。 */
export function InlineConfirm({
  title,
  body,
  confirmLabel,
  pending,
  onConfirm,
  onCancel,
}: {
  title: string;
  /** 一句话,或几条要先知道的事(下载走哪条路、令牌带不带得过去) */
  body?: React.ReactNode;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useI18n();
  return (
    <div role="group" aria-label={title} className="grid gap-2 rounded-lg border border-primary/40 bg-panel p-2.5 text-ui-xs">
      <p className="m-0 font-medium text-foreground">{title}</p>
      {body && <div className="m-0 grid gap-1 leading-relaxed text-muted-foreground">{body}</div>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="xs" disabled={pending} onClick={onCancel}>{t("cancel")}</Button>
        <Button size="xs" loading={pending} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </div>
  );
}

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export const jobDone = (job: Pick<Job, "status"> | undefined | null) => Boolean(job && TERMINAL.has(job.status));

/** 盯着一个后台任务(装节点包、下模型、跑一次):没完就每秒问一次,完了不再问。 */
export function useJobWatch(jobId: string | null, initial?: Job) {
  return useQuery({
    queryKey: ["jobs", "workbench", jobId],
    queryFn: () => getJob(jobId!),
    enabled: Boolean(jobId),
    initialData: initial,
    refetchInterval: (query) => (jobDone(query.state.data) ? false : 1000),
  });
}

/** 任务完成的那一下(从没完到完)只做一次。 */
export function useOnJobDone(job: Job | undefined, onDone: (job: Job) => void) {
  const seen = React.useRef<string | null>(null);
  const latest = React.useRef(onDone);
  React.useEffect(() => {
    latest.current = onDone;
  }, [onDone]);
  React.useEffect(() => {
    if (job && jobDone(job) && seen.current !== job.id) {
      seen.current = job.id;
      latest.current(job);
    }
  }, [job]);
}
