import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type AgentSession = components["schemas"]["AgentSessionOut"];
type CapabilityModel = components["schemas"]["CapabilityModelOut"];

const LEVELS = ["off", "low", "medium", "high"] as const;

/**
 * 这个模型能给几档。
 *
 * **不支持思考的模型不该有这个控件** —— 一个点了没用的开关比没有开关更坏:它让人以为
 * 关掉就不思考了,而事实是这个模型压根不思考,或者(反过来)它无论如何都会思考。
 *
 * 只能开/关的(DeepSeek、Qwen 这类混合模型)给两档:供应商那边只认"要不要",没有 effort。
 * 给出低/中/高只是让人挑一个发不出去的值。
 *
 * **拿不准的时候给全档**(reasoning 为 null:端点没报、或者这条连接还没细分过能力)。
 * 少一个档位是"想深想但没得选",多一个档位最多是"选了个没生效的值" —— 前者更坏。
 */
function levelsFor(model: CapabilityModel | undefined): readonly string[] {
  if (model?.reasoning === false) return [];
  if (model?.reasoning === true && model.reasoning_effort !== true) return ["off", "low"] as const;
  return LEVELS;
}

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
  // 与模型选择器读同一份清单(同一个 queryKey → 同一份缓存,不多打一次请求)。
  const models = useQuery({
    queryKey: ["capability-models", "chat"],
    queryFn: () => api<CapabilityModel[]>("/api/settings/capability-models/chat"),
    staleTime: 60_000,
  });
  const current = (models.data ?? []).find(
    (item) => item.model === session?.model && item.provider_profile_id === session?.provider_profile_id,
  );
  const levels = levelsFor(current);
  if (!session) return null;
  // 这个模型不思考 —— 不给控件,而不是给一个点了没用的。
  if (levels.length === 0) return null;
  const raw = levels.includes(session.thinking_level) ? session.thinking_level : "off";
  // 只能开/关的模型上,会话里存着的 medium/high 要落到"开"这一档,否则触发器是空的。
  const value = raw === "off" || levels.includes(raw) ? raw : levels[1] ?? "off";
  const binary = levels.length === 2;
  const label = (level: string) =>
    // 只有两档时,「低」这个名字没有意义 —— 它不是三档里的低,它就是"开"。
    binary && level === "low"
      ? t("agentThinkingOn")
      : level === "low"
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
        {levels.map((level) => (
          <SelectItem key={level} value={level}>
            {label(level)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
