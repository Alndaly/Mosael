import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { FIELD_TRIGGER_CLASS } from "@/components/ui/field-trigger";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useEffectiveChatModel } from "@/features/ai-studio/effectiveModel";
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
  // **不能直接拿 session.model 去匹配**:它平时是空的(会话跟默认走),空值匹配不上目录里
  // 任何一行,于是每个没手动指定模型的会话都被判成"发不出档位"。见 effectiveModel 的说明。
  const effective = useEffectiveChatModel(session);
  const current = (models.data ?? []).find(
    (item) => item.model === effective.model && item.provider_profile_id === effective.providerProfileId,
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
    const reason = models.isPending || effective.pending ? t("modelListLoading") : t("agentThinkingUnavailable");
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
  /*
   * **「没挑过」这个状态一直都在,清单里就得有它。**
   *
   * 会话的 thinking_level 建表默认是 `off`(见 db/models.py),而关不掉的模型(k3)清单里
   * 没有 `off` —— 于是 Select 拿着一个清单里不存在的值,Radix 找不到对应的 ItemText,
   * **触发器整个是空的**。每一个 k3 会话打开都是这样,而它正是这个功能要解决的那个模型。
   *
   * 补一档,但**不叫「关闭」**:我们确实没有关掉它(k3 关不掉),我们只是没提要求,由模型
   * 自己决定 —— 所以这一档叫「模型默认」。这和当初那个 bug 不是一回事:那时的错在于嘴上说
   * 「关闭」而实际什么都没发生;现在说的就是实际发生的事。
   */
  const offered = levels.includes("off") ? levels : ["off", ...levels];
  const value = offered.includes(session.thinking_level) ? session.thinking_level : "off";
  // 只有开/关两档时,「低」这个名字没有意义 —— 它不是三档里的低,它就是"开"。
  // 判据看**这个清单**有几档:k3 补上「模型默认」之后是三档,那时「低」就是低。
  const binary = offered.length === 2;
  const label = (level: string) =>
    level === "off"
      ? levels.includes("off")
        ? t("agentThinkingOff")
        : t("agentThinkingModelDefault")
      : binary && level === "low"
        ? t("agentThinkingOn")
        : level === "low"
          ? t("agentThinkingLow")
          : level === "medium"
            ? t("agentThinkingMedium")
            : t("agentThinkingHigh");
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
        {offered.map((level) => (
          <SelectItem key={level} value={level}>
            {label(level)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
