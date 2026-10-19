import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 工具名 —— **只有这一种排法**。
 *
 * 它是代码标识符(`edit_workflow`),不是散文,所以走等宽 —— 和对话正文里那些
 * `parse_scenes` 之类的内联代码是同一类东西。此前「最近工具」用无衬线 11.5px、
 * 「全部工具」弹层用等宽 12px/650:同一批名字换个地方看就换一种样子,
 * 这正是它读起来"字号怪怪的"的原因。
 *
 * (状态圈和工具名原先挤在 `StatusIcon.tsx` 里;那一行现在归检查器所有行共用,
 * 搬去了 `components/layout/InspectorStatusRow`,这里只留工具名。)
 */
export function ToolName({ name, className }: { name: string; className?: string }) {
  return (
    <Truncate className={cn("font-mono text-ui-sm font-[650] text-foreground", className)}>{name}</Truncate>
  );
}
