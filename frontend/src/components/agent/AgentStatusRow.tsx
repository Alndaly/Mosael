import React from "react";
import { Loader2 } from "lucide-react";

import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { AGENT_ROW_CLASS, AGENT_ROW_ICON_CLASS } from "@/components/agent/agentRow";
import { cn } from "@/lib/utils";

/**
 * 「还在跑」的那一行。
 *
 * 它和工具调用、思考块是**同一类东西** —— 这一步在做什么 —— 所以走同一个 Marker、同一个
 * 左缘、同一个图标栏(见 agentRow)。
 *
 * **耗时靠右,不跟在文案后面。** 工具行的耗时排在自己那一栏的右缘,上下几行对齐成一列;
 * 而这一行此前是「智能体思考中… 已用 1.0s」两截贴着写,读起来像半句话,而且和上面每一行的
 * 耗时都对不上。中间那段可伸缩的空白由 flex-1 占着,和 ToolCallCard 里那个占位是同一招。
 *
 * 四个调用点(画布助手 / 对话页 × 出没出正文)此前各写了一份,写出了四种:有的没有内缩、
 * 有的字号从外层继承成 text-ui-md、有的 mt-1.5 有的 gap-[7px]。
 */
export function AgentStatusRow({
  label,
  meta,
  className,
}: {
  /** 在做什么。省略时这一行就只有耗时(正文已经在流式输出,不必再说一遍"在思考")。 */
  label?: string;
  /** 靠右那一栏:耗时。 */
  meta: string;
  className?: string;
}) {
  return (
    <Marker className={cn(AGENT_ROW_CLASS, "text-muted-foreground", className)}>
      <MarkerIcon>
        <Loader2 className={cn(AGENT_ROW_ICON_CLASS, "animate-mosael-spin")} />
      </MarkerIcon>
      <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
        {label && <span className="flex-none">{label}</span>}
        <span className="min-w-0 flex-1" aria-hidden />
        <span className="timecode flex-none pl-1.5 tabular-nums">{meta}</span>
      </MarkerContent>
    </Marker>
  );
}
