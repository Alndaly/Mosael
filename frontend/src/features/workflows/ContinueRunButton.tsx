import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { continueWorkflowRun, type Job, type WorkflowContinueRequest } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell, ModalSubmit } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import type { Step } from "@/features/workflows/runSteps";

const LOOP_TYPES = new Set(["loop_foreach", "loop_while"]);
const NO_LOOP = "none";

/** 这次运行能不能接着跑:失败或被取消的、不是别的工作流调起来的(子运行由外层接着跑时重新调)。 */
export function canContinueRun(job: Job): boolean {
  return (job.status === "failed" || job.status === "cancelled") && !job.parent_job_id;
}

/** 这次运行里能重做的循环。成功的运行也能从某一轮重做。 */
function loopsOf(steps: Step[]): Step[] {
  return steps.filter((step) => step.nodeType && LOOP_TYPES.has(step.nodeType));
}

function useContinueRun(workflowId: string, jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WorkflowContinueRequest) => continueWorkflowRun(workflowId, jobId, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] }),
    onError: (error: Error) => toast.error(errorText(error)),
  });
}

/** 开始参数里改过的那几格,按原来的类型交回去。 */
function changedParams(original: Record<string, unknown>, draft: Record<string, string>): Record<string, unknown> {
  const changed = Object.entries(draft).filter(([key, value]) => value !== String(original[key] ?? ""));
  return Object.fromEntries(changed.map(([key, value]) => [key, typeof original[key] === "number" ? Number(value) : value]));
}

/**
 * 「调整后继续」:改开始参数(调高花费上限、换尾巴长度),或者选一个循环从第几轮重做、换掉那一轮的内容(ADR 0092)。
 * 跑完的节点不受影响:参数只对还没落定的节点生效,重做只动那一轮之后和循环的下游。
 */
function AdjustRunDialog({ workflowId, job, steps, open, onOpenChange }: {
  workflowId: string;
  job: Job;
  steps: Step[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useI18n();
  const resume = useContinueRun(workflowId, job.id);
  const params = steps.find((step) => step.nodeType === "start")?.outputs ?? {};
  const loops = loopsOf(steps);
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [loop, setLoop] = React.useState(NO_LOOP);
  const [round, setRound] = React.useState("1");
  const [item, setItem] = React.useState("");
  const values = { ...Object.fromEntries(Object.entries(params).map(([key, value]) => [key, String(value ?? "")])), ...draft };
  const redoing = loop !== NO_LOOP;
  const finished = job.status === "succeeded";

  function submit() {
    resume.mutate(
      {
        params: changedParams(params, values),
        ...(redoing ? { redo: { node_id: loop, index: Math.max(0, Number(round) - 1), ...(item.trim() ? { item } : {}) } } : {}),
      },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("wfRunAdjustTitle")}
      onSubmit={() => (!finished || redoing) && submit()}
      footer={<ModalSubmit loading={resume.isPending} disabled={finished && !redoing}>{t("wfRunAdjustSubmit")}</ModalSubmit>}
    >
      <div className="grid gap-3">
        {loops.length > 0 && (
          <div className="grid gap-2" data-run-redo="">
            <span className="text-ui-xs text-muted-foreground">{t("wfRunRedoLoop")}</span>
            <Select value={loop} onValueChange={setLoop}>
              <SelectTrigger aria-label={t("wfRunRedoLoop")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_LOOP}>{t("wfRunRedoNone")}</SelectItem>
                {loops.map((step) => <SelectItem key={step.nid} value={step.nid}>{step.name}</SelectItem>)}
              </SelectContent>
            </Select>
            {redoing && (
              <>
                <Input aria-label={t("wfRunRedoRound")} placeholder={t("wfRunRedoRound")} type="number" min={1} value={round} onChange={(event) => setRound(event.target.value)} />
                <Textarea aria-label={t("wfRunRedoItem")} placeholder={t("wfRunRedoItem")} rows={3} value={item} onChange={(event) => setItem(event.target.value)} />
              </>
            )}
          </div>
        )}
        {Object.keys(values).length > 0 && (
          <div className="grid gap-2" data-run-params="">
            <span className="text-ui-xs text-muted-foreground">{t("wfRunAdjustParams")}</span>
            {Object.entries(values).map(([key, value]) => (
              <label key={key} className="grid grid-cols-[10rem_1fr] items-center gap-2 text-ui-xs">
                <Truncate>{key}</Truncate>
                <Input aria-label={key} value={value} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
              </label>
            ))}
          </div>
        )}
      </div>
    </ModalShell>
  );
}

/**
 * 「从中断处继续」:已经跑完的节点(循环里跑完的那几轮)不再执行、不再花钱,失败的那一步重跑(ADR 0092)。
 * 接着跑的还是这一条运行,钉住的还是当时那一版图 —— 中途改过图也不影响它。
 */
export function ContinueRunActions({ workflowId, job, steps }: { workflowId: string; job: Job; steps: Step[] }) {
  const t = useI18n();
  const resume = useContinueRun(workflowId, job.id);
  const [adjusting, setAdjusting] = React.useState(false);
  const continuable = canContinueRun(job);
  const redoable = job.status === "succeeded" && !job.parent_job_id && loopsOf(steps).length > 0;
  if (!continuable && !redoable) return null;
  return (
    <>
      <Hint label={t("wfRunAdjustHint")}>
        <Button size="sm" variant="outline" className="shrink-0" onClick={() => setAdjusting(true)}>
          <SlidersHorizontal size={13} /> {t(continuable ? "wfRunAdjust" : "wfRunRedo")}
        </Button>
      </Hint>
      {continuable && (
        <Hint label={t("wfRunContinueHint")}>
          <Button size="sm" variant="outline" className="shrink-0" loading={resume.isPending} onClick={() => resume.mutate({})}>
            <Play size={13} /> {t("wfRunContinue")}
          </Button>
        </Hint>
      )}
      {adjusting && <AdjustRunDialog workflowId={workflowId} job={job} steps={steps} open onOpenChange={setAdjusting} />}
    </>
  );
}
