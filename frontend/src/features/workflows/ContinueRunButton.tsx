import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { toast } from "sonner";

import { continueWorkflowRun, type Job } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";

/** 这次运行能不能接着跑:失败或被取消的、不是别的工作流调起来的(子运行由外层接着跑时重新调)。 */
export function canContinueRun(job: Job): boolean {
  return (job.status === "failed" || job.status === "cancelled") && !job.parent_job_id;
}

/**
 * 「从中断处继续」:已经跑完的节点(循环里跑完的那几轮)不再执行、不再花钱,失败的那一步重跑(ADR 0092)。
 * 接着跑的还是这一条运行,钉住的还是当时那一版图 —— 中途改过图也不影响它。
 */
export function ContinueRunButton({ workflowId, jobId }: { workflowId: string; jobId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const resume = useMutation({
    mutationFn: () => continueWorkflowRun(workflowId, jobId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] }),
    onError: (error: Error) => toast.error(errorText(error)),
  });
  return (
    <Hint label={t("wfRunContinueHint")}>
      <Button size="sm" variant="outline" className="shrink-0" loading={resume.isPending} onClick={() => resume.mutate()}>
        <Play size={13} /> {t("wfRunContinue")}
      </Button>
    </Hint>
  );
}
