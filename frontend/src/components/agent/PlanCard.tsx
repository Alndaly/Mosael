import React from "react";
import { ListChecks } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { AgentStatusIcon, toAgentStatus } from "@/components/agent/StatusIcon";
import { InspectorCard } from "@/components/agent/InspectorCard";
import type { AgentTimelineItem } from "@/components/agent/ToolCalls";
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
/** 从时间线里的 update_plan 调用还原出「做过的那几件事」。
 *
 * **不为此新开一张表**:每次改计划都会留下一次工具调用,参数里就是当时那张清单 ——
 * 历史本来就在,只是没人去读。
 *
 * 关键是**归并**:模型在同一件事里会反复调 update_plan 来推进状态(做完一步就报一次),
 * 那些是同一份计划的连续快照,不是"第 1 版、第 2 版"—— 把每次调用都陈列出来,得到的是
 * 同样三行、只有勾变了的一摞噪音。所以相邻两次只要**步骤文本有一半以上重合**就算同一份,
 * 只留最后那次(也就是它最终的样子);换了新活儿(清单整体不同)才另起一份。
 */
export function planHistory(timelines: (AgentTimelineItem[] | undefined)[]): PlanStep[][] {
  const plans: PlanStep[][] = [];
  for (const timeline of timelines) {
    for (const item of timeline ?? []) {
      if (item.type !== "tool" || item.tool?.name !== "update_plan") continue;
      const steps = readSteps(item.tool.args);
      if (steps.length === 0) continue;
      const last = plans[plans.length - 1];
      if (last && samePlan(last, steps)) plans[plans.length - 1] = steps;
      else plans.push(steps);
    }
  }
  return plans;
}

/** 两张清单是不是同一份计划的两次快照:步骤文本重合过半就算。 */
function samePlan(a: PlanStep[], b: PlanStep[]): boolean {
  const texts = new Set(a.map((step) => step.step));
  const shared = b.filter((step) => texts.has(step.step)).length;
  return shared * 2 >= Math.min(a.length, b.length);
}

function readSteps(args: unknown): PlanStep[] {
  let value: unknown = args;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return [];
    }
  }
  const steps = (value as { steps?: unknown } | null)?.steps;
  if (!Array.isArray(steps)) return [];
  return steps
    .map((step) =>
      typeof step === "string"
        ? { step, status: "pending" }
        : { step: String((step as PlanStep).step ?? ""), status: String((step as PlanStep).status ?? "pending") },
    )
    .filter((step) => step.step);
}

export function PlanCard({
  plan,
  history = [],
  className,
}: {
  plan: PlanStep[] | null | undefined;
  /** 历次计划(旧→新)。当前这份做完之后,卡片改为陈列它们。 */
  history?: PlanStep[][];
  className?: string;
}) {
  const t = useI18n();
  const steps = plan ?? [];
  const done = steps.filter((step) => step.status === "done").length;
  const allDone = steps.length > 0 && done === steps.length;
  const [open, setOpen] = React.useState(true);

  // 计划的用处在**进行中**。全做完(或压根没有)之后,当前这份就只是上一件事的残留 ——
  // 模型本该 update_plan([]) 清掉,但它常常忘,于是下一轮开口时侧栏还挂着上一件事的清单
  // (真机反馈:「所有任务都完成之后还显示着之前的任务」)。
  // 这时卡片改为陈列**历次计划**:默认折叠,想回看再展开。两者都没有才整块不渲染。
  const showingHistory = steps.length === 0 || allDone;
  if (showingHistory && history.length === 0) return null;

  return (
    // 外壳与检查器其余各块共用 —— 此前它自己写了一份几乎一样但又不完全一样的标题行。
    <InspectorCard
      icon={ListChecks}
      title={showingHistory ? t("agentPlanHistory") : t("agentPlan")}
      aside={showingHistory ? String(history.length) : `${done}/${steps.length}`}
      onToggle={() => setOpen((value) => !value)}
      open={open}
      className={className}
    >
      {open && showingHistory && (
        // 历次计划,新的在上。每一份就是当时那张清单,原样陈列。
        <div className="grid gap-2">
          {[...history].reverse().map((past, index) => (
            <div className="grid gap-1" key={index}>
              {/* 不编号 —— 它们不是"版本",是先后做过的几件事。标完成度就够了。 */}
              <span className="text-ui-2xs tabular-nums text-muted-foreground">
                {past.filter((step) => step.status === "done").length}/{past.length}
              </span>
              <PlanSteps steps={past} />
            </div>
          ))}
        </div>
      )}
      {open && !showingHistory && <PlanSteps steps={steps} />}
    </InspectorCard>
  );
}

function PlanSteps({ steps }: { steps: PlanStep[] }) {
  return (
    <>
      {(
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
    </>
  );
}
