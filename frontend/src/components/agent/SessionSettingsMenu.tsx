import React from "react";
import { Scissors, SlidersHorizontal } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ContextMeter, type ContextInfo } from "@/components/agent/ContextMeter";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { AnalysisModePicker } from "@/features/ai-studio/AnalysisModePicker";
import { ThinkingLevelPicker } from "@/features/ai-studio/ThinkingLevelPicker";

type AgentSession = components["schemas"]["AgentSessionOut"];

/**
 * 输入框上的「会话设置」——分析方式、思考档位、上下文整理收进一个弹出层。
 *
 * **为什么收起来**:此前它们和模式切换、附件、模型、水位、发送一起平铺在一行,八个控件挤在
 * 输入框下方,最常用的(打字、发送)和最少用的(分析方式)权重完全一样。按使用频率分层之后,
 * 主行只留每次都要看的三样,其余进这里 —— 它们是"配好就不再动"的东西。
 *
 * **两个页面共用**:AI Studio 和工作流助手此前各写各的工具行,同一个功能在两边的位置、
 * 顺序、有无都不一致。抽成一个组件,改一次两边同时生效。
 */
export function SessionSettingsMenu({
  session,
  context,
  onCompact,
  compacting,
  showAnalysis = true,
}: {
  session: AgentSession | null;
  context?: ContextInfo | null;
  onCompact?: () => void;
  compacting?: boolean;
  /** 工作流助手不做素材分析,那一项在它那儿是死的。 */
  showAnalysis?: boolean;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  if (!session) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={t("agentSessionSettings")}
          title={t("agentSessionSettings")}
        >
          <SlidersHorizontal size={13} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="grid w-[260px] gap-2.5 p-2.5">
        <div className="grid gap-1.5">
          <span className="text-[11px] font-medium text-muted-foreground">{t("agentThinkingLevel")}</span>
          <ThinkingLevelPicker session={session} />
        </div>
        {showAnalysis && (
          <div className="grid gap-1.5">
            <span className="text-[11px] font-medium text-muted-foreground">{t("analysisModeLabel")}</span>
            <AnalysisModePicker session={session} />
          </div>
        )}
        {/* 水位与「立即整理」放在一起:它们是同一件事的两半 —— 看还剩多少、据此决定要不要整理。
            拆开放会让读数变成一个没有下文的数字,而按钮变成一个不知道该不该按的操作。
            输入框那一行因此不再重复显示它。 */}
        {context && context.window > 0 && (
          <div className="grid gap-2 border-t border-border pt-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-muted-foreground">{t("agentContextTitle")}</span>
              <ContextMeter context={context} compacting={compacting} />
            </div>
            {onCompact && (
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={compacting}
                // **不关弹出层**:水位条就在这个按钮上面,整理的结果(剩余百分比变化)
                // 恰恰在这里显示。关掉它等于把用户刚触发的那件事的结果藏起来。
                onClick={() => onCompact()}
              >
                <Scissors size={12} /> {t("agentCompactNow")}
              </Button>
            )}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
