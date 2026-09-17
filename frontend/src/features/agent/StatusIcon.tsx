import { Circle, CircleCheck, CircleDot, CircleX } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 检查器里「这一条现在怎么样了」的图标 —— **只有这一种**。
 *
 * 计划步骤和工具调用说的是同一件事(做完了 / 正在做 / 失败了 / 还没开始),此前却各画各的:
 * 计划用 12px 的 lucide 圆圈,工具用一个 7px 的色点。并排放在同一个面板里,眼睛会以为它们是
 * 两类东西 —— 而且那个 7px 是整个面板里独此一处的尺寸。
 *
 * 两边的状态词不一样(计划说 in_progress,工具说 running),所以在这里归一,而不是逼一边改名。
 */
export type AgentStatus = "done" | "running" | "error" | "pending";

export function toAgentStatus(raw: string | null | undefined): AgentStatus {
  if (raw === "done") return "done";
  if (raw === "running" || raw === "in_progress") return "running";
  if (raw === "error" || raw === "failed") return "error";
  return "pending";
}

const ICONS = {
  done: { Icon: CircleCheck, className: "text-success" },
  running: { Icon: CircleDot, className: "animate-pulse text-primary" },
  error: { Icon: CircleX, className: "text-destructive" },
  pending: { Icon: Circle, className: "text-muted-foreground/60" },
} as const;

export function AgentStatusIcon({
  status,
  className,
  size = 12,
}: {
  status: AgentStatus;
  className?: string;
  size?: number;
}) {
  const { Icon, className: tone } = ICONS[status];
  return <Icon size={size} className={cn("shrink-0", tone, className)} aria-hidden />;
}

/**
 * 工具名 —— **只有这一种排法**。
 *
 * 它是代码标识符(`edit_workflow`),不是散文,所以走等宽 —— 和对话正文里那些
 * `parse_scenes` 之类的内联代码是同一类东西。此前「最近工具」用无衬线 11.5px、
 * 「全部工具」弹层用等宽 12px/650:同一批名字换个地方看就换一种样子,
 * 这正是它读起来"字号怪怪的"的原因。
 */
export function ToolName({ name, className }: { name: string; className?: string }) {
  return (
    <span className={cn("min-w-0 truncate font-mono text-ui-sm font-[650] text-foreground", className)} title={name}>
      {name}
    </span>
  );
}
