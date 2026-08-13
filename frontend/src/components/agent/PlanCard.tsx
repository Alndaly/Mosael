import React from "react";
import { ListChecks } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { AgentStatusIcon, toAgentStatus } from "@/components/agent/StatusIcon";
import { InspectorCard } from "@/components/agent/InspectorCard";
import { cn } from "@/lib/utils";

export type PlanStep = { step: string; status: "pending" | "in_progress" | "done" | string };

/**
 * 任务计划:模型打算做什么、做到哪了。
 *
 * **为什么值得占一块地方**:多步骤任务里,用户此前只能从流水一样的工具卡里猜进度 ——
 * 而"它还要做几步""刚才那步做完没有"是等待时唯一想知道的事。Codex 的 update_plan、
 * Claude Code 的待办列表解决的是同一个问题。
 *
 * 全部做完就折叠成一行:计划的用处在**进行中**,做完之后它只是历史。
 */
export function PlanCard({ plan, className }: { plan: PlanStep[] | null | undefined; className?: string }) {
  const t = useI18n();
  const steps = plan ?? [];
  const done = steps.filter((step) => step.status === "done").length;
  const allDone = steps.length > 0 && done === steps.length;
  const [open, setOpen] = React.useState(true);
  // 全做完之后自动收起一次(用户仍可再展开)。放 effect 里而不是直接用 allDone 当 open,
  // 是为了不夺走用户手动展开的权利。
  const wasAllDone = React.useRef(allDone);
  React.useEffect(() => {
    if (allDone && !wasAllDone.current) setOpen(false);
    wasAllDone.current = allDone;
  }, [allDone]);

  if (steps.length === 0) return null;

  return (
    // 外壳与检查器其余各块共用 —— 此前它自己写了一份几乎一样但又不完全一样的标题行。
    <InspectorCard
      icon={ListChecks}
      title={t("agentPlan")}
      aside={`${done}/${steps.length}`}
      onToggle={() => setOpen((value) => !value)}
      className={className}
    >
      {open && (
        <ol className="m-0 grid list-none gap-1 p-0">
          {steps.map((step, index) => (
            <li
              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5 text-ui-xs leading-[1.5]"
              key={`${index}-${step.step}`}
            >
              <AgentStatusIcon status={toAgentStatus(step.status)} className="mt-[3px]" />
              <span
                className={cn(
                  "min-w-0 break-words",
                  step.status === "done" && "text-muted-foreground line-through decoration-muted-foreground/50",
                  step.status === "in_progress" && "font-medium text-foreground",
                  step.status !== "done" && step.status !== "in_progress" && "text-muted-foreground",
                )}
              >
                {step.step}
              </span>
            </li>
          ))}
        </ol>
      )}
    </InspectorCard>
  );
}
