import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

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
      queryFn: () => api<string[]>(`/api/settings/providers/${profile.id}/models`),
      staleTime: 60_000,
    })),
  });

  const options = enabled.flatMap((profile, index) => {
    const models = new Set(modelQueries[index].data ?? []);
    if (profile.default_model) models.add(profile.default_model);
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

  if (!session || options.length === 0) return null;
  const currentProfileId = session.provider_profile_id ?? defaultChat?.provider_profile_id ?? "";
  const currentModel = session.model ?? defaultChat?.model ?? "";
  const current = currentProfileId && currentModel ? `${currentProfileId}${SEP}${currentModel}` : "";

  return (
    // key 随 current 变化重挂,规避 Radix 对初始受控值不刷新显示文本的问题
    <Select key={current || "none"} value={current} onValueChange={(value) => setModel.mutate(value)}>
      <SelectTrigger className="h-7 w-auto min-w-0 max-w-[220px] gap-1 px-2 text-xs text-muted-foreground" aria-label={t("agentModelLabel")}>
        <SelectValue placeholder={t("agentModelPlaceholder")} />
      </SelectTrigger>
      <SelectContent className="max-w-none">
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
