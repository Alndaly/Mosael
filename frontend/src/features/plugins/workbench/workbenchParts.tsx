/**
 * 工作台面板里几处共用的小件。面板画在内嵌画布旁边那一列,原生网页视图盖在一切 DOM 上 —— 居中的弹窗会被画布盖住,
 * 所以要确认的事就地确认(`InlineConfirm`),不弹框。
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Info, TriangleAlert } from "lucide-react";

import { getJob, type Job } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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
  body?: string;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useI18n();
  return (
    <div role="group" aria-label={title} className="grid gap-2 rounded-lg border border-primary/40 bg-panel p-2.5 text-ui-xs">
      <p className="m-0 font-medium text-foreground">{title}</p>
      {body && <p className="m-0 leading-relaxed text-muted-foreground">{body}</p>}
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
