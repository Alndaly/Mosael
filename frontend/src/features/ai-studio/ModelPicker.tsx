import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Settings2 } from "lucide-react";

import { api, listProviderModels } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { gotoSettings } from "@/lib/deepLink";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];
type ProviderDefault = components["schemas"]["ProviderDefaultOut"];

const SEP = "::";

/**
 * 对话模型选择器:列出每个启用供应商的可用模型(经 /providers/{id}/models),
 * 选中后写回会话的 provider_profile_id + model。会话未选则后端回退默认。
 */
export function ModelPicker({ workspaceId, session }: { workspaceId: string; session: AgentSession | null }) {
  const t = useI18n();
  const qc = useQueryClient();

  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
  });
  const enabled = (providers.data ?? []).filter((profile) => profile.enabled);
  const defaultChat = (defaults.data ?? []).find((item) => item.capability === "chat");

  const modelQueries = useQueries({
    queries: enabled.map((profile) => ({
      queryKey: ["provider-models", profile.id],
      queryFn: () => listProviderModels(profile.id),
      staleTime: 60_000,
    })),
  });

  const options = enabled.flatMap((profile, index) => {
    const models = new Set((modelQueries[index].data ?? []).map((m) => m.id));
    if (defaultChat?.provider_profile_id === profile.id && defaultChat.model) models.add(defaultChat.model);
    if (session?.provider_profile_id === profile.id && session.model) models.add(session.model);
    return [...models].map((model) => ({
      value: `${profile.id}${SEP}${model}`,
      label: enabled.length > 1 ? `${profile.name} · ${model}` : model,
    }));
  });

  const setModel = useMutation({
    mutationFn: (value: string) => {
      const [providerProfileId, ...rest] = value.split(SEP);
      return api(`/api/agent/sessions/${session!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ provider_profile_id: providerProfileId, model: rest.join(SEP) }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-session", session?.id] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
    },
  });

  const loading = providers.isPending || defaults.isPending || modelQueries.some((query) => query.isPending);
  const failed = providers.isError || defaults.isError || modelQueries.some((query) => query.isError);
  if (loading || failed) return null;
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
  if (!session) return null;
  const currentProfileId = session.provider_profile_id ?? defaultChat?.provider_profile_id ?? "";
  const currentModel = session.model ?? defaultChat?.model ?? "";
  const current = currentProfileId && currentModel ? `${currentProfileId}${SEP}${currentModel}` : "";
  const currentLabel = options.find((option) => option.value === current)?.label ?? t("agentModelPlaceholder");

  // 供应商(如火山)可能一次暴露几十个模型,普通下拉会顶穿屏幕 → 可搜索、封顶高度的选择器。
  return (
    <SearchableSelect
      value={current}
      onValueChange={(value) => setModel.mutate(value)}
      options={options}
      searchPlaceholder={t("agentModelPlaceholder")}
      emptyText={t("cmdkEmpty")}
      trigger={
        <button
          type="button"
          aria-label={t("agentModelLabel")}
          className="inline-flex h-7 w-auto min-w-0 max-w-[220px] items-center gap-1 rounded-md border border-input bg-field px-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
        >
          <span className="truncate">{currentLabel}</span>
          <ChevronDown size={13} className="shrink-0 opacity-50" />
        </button>
      }
    />
  );
}
