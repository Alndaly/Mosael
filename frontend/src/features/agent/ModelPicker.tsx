import React from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronDown, Loader2, Settings2 } from "lucide-react";

import { listProviderDefaults, listProviderModels, listProviderProfiles } from "@/api/client";
import { providerKeys } from "@/api/queryKeys";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import { useUpdateAgentSession } from "@/features/agent/currentAgentSession";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Truncate } from "@/components/ui/truncate";
import { gotoSettings } from "@/lib/deepLink";

type AgentSession = components["schemas"]["AgentSessionOut"];

const SEP = "::";

/**
 * 对话模型选择器:列出每个启用供应商的可用模型(经 /providers/{id}/models),
 * 选中后写回会话的 provider_profile_id + model。会话未选则后端回退默认。
 *
 * 还没有会话时显示默认模型、照样能选:选了就先建出当前会话再写进去(见 useUpdateAgentSession)。
 */
export function ModelPicker({ workspaceId, session }: { workspaceId: string; session: AgentSession | null }) {
  const t = useI18n();

  const providers = useQuery({
    queryKey: providerKeys.profiles(),
    queryFn: listProviderProfiles,
  });
  const defaults = useQuery({
    queryKey: providerKeys.defaults(),
    queryFn: listProviderDefaults,
  });
  const enabled = (providers.data ?? []).filter((profile) => profile.enabled);
  const defaultChat = (defaults.data ?? []).find((item) => item.capability === "chat");
  // 「这轮实际用哪个模型」只有一处算法(effectiveModel),思考档位那边用的是同一个。
  const effective = useEffectiveChatModel(session);

  const modelQueries = useQueries({
    queries: enabled.map((profile) => ({
      queryKey: providerKeys.models(profile.id),
      queryFn: () => listProviderModels(profile.id),
      staleTime: 60_000,
    })),
  });

  //: 读失败的那条连接给空数组 —— 它不该把别的连接的模型一起带走。
  const options = enabled.flatMap((profile, index) => {
    const models = new Set((modelQueries[index].data ?? []).map((m) => m.id));
    if (defaultChat?.provider_profile_id === profile.id && defaultChat.model) models.add(defaultChat.model);
    if (session?.provider_profile_id === profile.id && session.model) models.add(session.model);
    return [...models].map((model) => ({
      value: `${profile.id}${SEP}${model}`,
      label: enabled.length > 1 ? `${profile.name} · ${model}` : model,
    }));
  });

  const update = useUpdateAgentSession(workspaceId, session);
  const setModel = (value: string) => {
    const [providerProfileId, ...rest] = value.split(SEP);
    update.mutate({ provider_profile_id: providerProfileId, model: rest.join(SEP) });
  };

  const loading = providers.isPending || defaults.isPending || modelQueries.some((query) => query.isPending);
  const failed = providers.isError || defaults.isError || modelQueries.some((query) => query.isError);

  /**
   * **这一格永远占着位置。**
   *
   * 此前只要「还在读」或「任何一条连接的模型列表出错」,整个选择器就 `return null` —— 控件凭空
   * 消失,而且不说为什么。两种后果都很坏:
   *
   * - 读取期间它闪没再闪回来,页面一慢就变成"模型选择框怎么没了"(用户报的就是这个);
   * - 某一条连接的端点挂了,会把**其余所有连接**的模型一起带走 —— 一条坏连接吃掉了整个功能。
   *
   * 现在:读取中显示一个禁用的占位(名字优先用会话上已经存着的那个,所以多数时候你看到的还是
   * 同一行字);一条出错不再影响别的,能读出来的照样能选。
   */
  if (loading) {
    return (
      <span
        role="status"
        className="inline-flex h-7 max-w-[220px] items-center gap-1 rounded-md border border-field-border bg-field px-2 text-xs text-muted-foreground opacity-70"
      >
        <Truncate>{session?.model || t("agentModelPlaceholder")}</Truncate>
        <Loader2 size={12} className="shrink-0 animate-mosael-spin" />
      </span>
    );
  }
  if (options.length === 0) {
    return (
      <Button
        type="button"
        variant="outline"
        size="xs"
        className="gap-1 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => gotoSettings("providers:chat")}
      >
        <Settings2 size={13} />
        {t("agentConfigureModel")}
      </Button>
    );
  }
  const { providerProfileId: currentProfileId, model: currentModel } = effective;
  const current = currentProfileId && currentModel ? `${currentProfileId}${SEP}${currentModel}` : "";
  const currentLabel = options.find((option) => option.value === current)?.label ?? t("agentModelPlaceholder");

  // 供应商(如火山)可能一次暴露几十个模型,普通下拉会顶穿屏幕 → 可搜索、封顶高度的选择器。
  return (
    <SearchableSelect
      value={current}
      onValueChange={setModel}
      options={options}
      searchPlaceholder={t("agentModelPlaceholder")}
      emptyText={t("cmdkEmpty")}
      //: 有连接读不出来时说一声 —— 少了几个模型总比"整个控件不见了"好,但也不能一声不吭。
      hint={failed ? t("agentModelSomeUnavailable") : undefined}
      trigger={
        <button
          type="button"
          aria-label={t("agentModelLabel")}
          className="inline-flex h-7 w-auto min-w-0 max-w-[220px] items-center gap-1 rounded-md border border-field-border bg-field px-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
        >
          <Truncate>{currentLabel}</Truncate>
          {/* 没有会话时这一下要先建会话再写,不止一个来回 —— 转圈说明"收到了,在办"。 */}
          {update.isPending ? (
            <Loader2 size={13} className="shrink-0 animate-mosael-spin" />
          ) : (
            <ChevronDown size={13} className="shrink-0 opacity-50" />
          )}
        </button>
      }
    />
  );
}
