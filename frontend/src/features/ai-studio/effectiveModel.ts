import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";

type AgentSession = components["schemas"]["AgentSessionOut"];
type ProviderDefault = components["schemas"]["ProviderDefaultOut"];

/**
 * 这次对话**实际用的是哪个模型**。
 *
 * 会话的 `model` / `provider_profile_id` 平时是**空的**:新建会话不写死模型,跟着「设置 →
 * AI 对话」的默认走,后端发请求时才回退(见 resolve_chat_provider)。数据库里几乎每一条会话
 * 这两列都是 NULL —— 也就是说,**「会话选了什么」和「这轮实际用什么」不是一回事**,而前者为空
 * 才是常态。
 *
 * 这件事此前有三份算法:ModelPicker 做了回退(所以它显示得对),ChatWorkspace 只回退了模型名
 * (够它显示一行字),而 ThinkingLevelPicker 直接拿 `session.model` 去匹配目录 —— 空值匹配不上
 * 任何一行,于是**任何没有手动指定模型的会话**,思考档位都显示「这条连接发不出思考档位」,
 * 哪怕那个模型明明支持。绝大多数会话都是这种,所以这个开关基本等于没有。
 *
 * 三处合并到这里。谁要问"现在用的是哪个模型",答案只有一个来源。
 */
export interface EffectiveChatModel {
  /** 供应商连接 id。空串 = 还不知道(默认值没到,或者一个都没配)。 */
  providerProfileId: string;
  /** 模型 id。空串同上。 */
  model: string;
  /**
   * 默认值还在路上。
   *
   * **「还不知道」和「问过了,没有」必须分开**:前者是暂时的,界面该说"读取中";后者是结论,
   * 界面才能说"发不出去"。把两者混成一个空值,读者看到的就是一个永远转不完的东西。
   */
  pending: boolean;
}

export function useEffectiveChatModel(session: AgentSession | null | undefined): EffectiveChatModel {
  // 与 ModelPicker / ChatWorkspace 同一个 queryKey —— 同一份缓存,不会多打一次请求。
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
    staleTime: 60_000,
  });
  const fallback = (defaults.data ?? []).find((item) => item.capability === "chat");
  return {
    providerProfileId: session?.provider_profile_id ?? fallback?.provider_profile_id ?? "",
    model: session?.model ?? fallback?.model ?? "",
    pending: defaults.isPending,
  };
}
