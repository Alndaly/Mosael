import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { FIELD_TRIGGER_CLASS } from "@/components/ui/field-trigger";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];
type CapabilityModel = components["schemas"]["CapabilityModelOut"];

/**
 * 这个模型**真正发得出去**的档位。
 *
 * 由后端按 vendor + 模型名给(见 backend/app/domain/thinking.py),不再在这里推 ——
 * 各家的思考参数不是同一套词,而**猜错一个值就是整轮 400**。查证过的几家才有档位,
 * 其余是空清单,界面据此说"这条连接发不出思考档位"。
 *
 * 这和「这个模型会不会思考」是两回事,而混淆它们正是用户报的那个 bug:选了「关闭」,
 * Kimi k3 照样在思考。查证下来 k3 **一直思考**(`reasoning_effort` 只收 low/high/max),
 * 所以正确的界面不是"关闭没生效",是这个模型压根不提供关闭 —— 而且它也没有「中」,
 * 此前那一档是个发出去会被拒的值。
 */
function levelsFor(model: CapabilityModel | undefined): readonly string[] {
  return model?.thinking_levels ?? [];
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

  /*
   * **发不出档位时也要占住这一格。**
   *
   * 标题「思考」是外面那个面板画的,不是这里 —— 这里返回 null 的话,面板上就留下一个
   * 底下什么都没有的标题(用户截图里正是如此:「思考」和「视频分析方式」之间是一片空)。
   * 所以给一个**和旁边两个下拉同形状的禁用输入**:位置还在、读得出为什么,只是按不动。
   *
   * 目录还没到(current 为空)时说的是「读取中」而不是「发不出去」:"还不知道"不能长成
   * 一个结论,而多数连接其实是发得出的。
   */
  if (!current || levels.length === 0) {
    /*
     * **「还在读」和「读完了但目录里没有这个模型」是两件事,后者是永久的。**
     *
     * 只看 `current` 为空的话,会话用的模型一旦不在 chat 目录里(换过连接、模型被停用、
     * 手填的别名),这一格就永远停在「读取模型…」—— 用户看到的是一个一直转不完的东西,
     * 而它其实已经有结论了:我们不认识这个模型,发不出档位。
     */
    const reason = models.isPending ? t("modelListLoading") : t("agentThinkingUnavailable");
    return (
      <button
        type="button"
        disabled
        className={cn(
          FIELD_TRIGGER_CLASS,
          "h-8 justify-start gap-1.5 px-2.5 text-xs text-muted-foreground",
        )}
        aria-label={reason}
        title={models.isPending ? reason : `${reason}\n${t("agentThinkingUnavailableHint")}`}
      >
        <Brain size={13} className="shrink-0 opacity-70" />
        <span className="min-w-0 truncate">{reason}</span>
      </button>
    );
  }
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
