import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Brain } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type AgentSession = components["schemas"]["AgentSessionOut"];

const LEVELS = ["off", "low", "medium", "high"] as const;

/**
 * 思考档位(会话级)。
 *
 * **「关闭」只表示我们不主动要求思考**,不表示模型不会思考:Kimi k3、DeepSeek reasoner
 * 这类模型无论如何都会返回思考内容,pi 照常解析、我们照常显示 —— 那是模型真实产出的东西,
 * 藏掉才是错的。它现在摆在「会话设置」里、上面挂着「思考」这个标题,管的是什么已经清楚,
 * 触发器里不再重复一遍。
 *
 * **挂在会话上而不是模型上**:同一个模型有时要深想、有时要快答 —— 它是每次对话的选择,
 * 不是模型的属性。所以入口跟着输入框走,和模型选择器并排,而不是藏在模型设置弹窗里。
 *
 * off 时 pi 根本不向供应商要思考(reasoning 传 undefined)。这与模型设置里的「推理模型」
 * 是两件事:后者只决定拿到思考内容后**怎么解析**,不决定要不要。
 */
export function ThinkingLevelPicker({ session }: { session: AgentSession | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const setLevel = useMutation({
    mutationFn: (level: string) =>
      api(`/api/agent/sessions/${session!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ thinking_level: level }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-session", session?.id] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions"] });
    },
  });
  if (!session) return null;
  const value = (LEVELS as readonly string[]).includes(session.thinking_level) ? session.thinking_level : "off";
  const label = (level: string) =>
    level === "low"
      ? t("agentThinkingLow")
      : level === "medium"
        ? t("agentThinkingMedium")
        : level === "high"
          ? t("agentThinkingHigh")
          : t("agentThinkingOff");
  return (
    // key 随 value 重挂,规避 Radix 对初始受控值不刷新触发器文本的问题(与分析方式同一处理)。
    <Select key={value} value={value} onValueChange={(next) => setLevel.mutate(next)}>
      <SelectTrigger
        className="h-8 w-full justify-between gap-1.5 px-2.5 text-xs text-muted-foreground"
        aria-label={t("agentThinkingLevel")}
        title={t("agentThinkingLevel")}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <Brain size={13} className="shrink-0 opacity-70" />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent className="max-w-none">
        {LEVELS.map((level) => (
          <SelectItem key={level} value={level}>
            {label(level)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
