import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type ProviderDefault = components["schemas"]["ProviderDefaultOut"];
type GenerationModel = components["schemas"]["GenerationModelOut"];

const NONE = "__none__";

/** 一行:某能力的默认供应商 + 模型。chat 的模型取自供应商 /models;image/video 取自生成目录(按 vendor 过滤)。 */
function DefaultRow({
  capability,
  label,
  providers,
  current,
  genModels,
}: {
  capability: string;
  label: string;
  providers: ProviderProfile[];
  current: ProviderDefault | undefined;
  genModels: GenerationModel[] | null;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const providerId = current?.provider_profile_id ?? "";
  const model = current?.model ?? "";
  const selectedProfile = providers.find((p) => p.id === providerId) ?? null;

  // chat:该供应商的 LLM 列表
  const chatModels = useQuery({
    queryKey: ["provider-models", providerId],
    queryFn: () => api<string[]>(`/api/settings/providers/${providerId}/models`),
    enabled: capability === "chat" && Boolean(providerId),
    staleTime: 60_000,
  });
  const modelOptions =
    capability === "chat"
      ? chatModels.data ?? []
      : (genModels ?? []).filter((m) => !selectedProfile || m.provider === selectedProfile.vendor).map((m) => m.model);

  const save = useMutation({
    mutationFn: (patch: { provider_profile_id: string | null; model: string }) =>
      api(`/api/settings/provider-defaults/${capability}`, { method: "PUT", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["provider-defaults"] }),
  });

  return (
    <div className="provider-default-row">
      <span className="provider-default-cap">{label}</span>
      <Select
        key={`p-${providerId || "none"}`}
        value={providerId || NONE}
        onValueChange={(value) => save.mutate({ provider_profile_id: value === NONE ? null : value, model: "" })}
      >
        <SelectTrigger className="provider-default-select">
          <SelectValue placeholder={t("kbEmbedPickProvider")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>—</SelectItem>
          {providers.map((profile) => (
            <SelectItem key={profile.id} value={profile.id}>
              {profile.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        key={`m-${model || "none"}`}
        value={model || NONE}
        onValueChange={(value) => save.mutate({ provider_profile_id: providerId || null, model: value === NONE ? "" : value })}
        disabled={!providerId || modelOptions.length === 0}
      >
        <SelectTrigger className="provider-default-select">
          <SelectValue placeholder={t("agentModelPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {modelOptions.map((name) => (
            <SelectItem key={name} value={name}>
              {name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function ProviderDefaultsSection() {
  const t = useI18n();
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
  });
  const genImage = useQuery({
    queryKey: ["generation-models", "image"],
    queryFn: () => api<GenerationModel[]>("/api/generation/models?kind=image"),
  });
  const genVideo = useQuery({
    queryKey: ["generation-models", "video"],
    queryFn: () => api<GenerationModel[]>("/api/generation/models?kind=video"),
  });

  const enabled = (providers.data ?? []).filter((profile) => profile.enabled);
  const byCapability = new Map((defaults.data ?? []).map((row) => [row.capability, row]));
  const rows: Array<{ capability: string; label: string; genModels: GenerationModel[] | null }> = [
    { capability: "chat", label: t("capChat"), genModels: null },
    { capability: "image", label: t("capImage"), genModels: genImage.data ?? null },
    { capability: "video", label: t("capVideo"), genModels: genVideo.data ?? null },
  ];

  return (
    <SettingsGroup title={t("providerDefaultsTitle")} description={t("providerDefaultsDesc")}>
      <SettingsBlock>
        {enabled.length === 0 ? (
          <p className="feishu-empty">{t("kbEmbedNoProvider")}</p>
        ) : (
          <div className="provider-defaults">
            {rows.map((row) => (
              <DefaultRow
                key={row.capability}
                capability={row.capability}
                label={row.label}
                providers={enabled}
                current={byCapability.get(row.capability)}
                genModels={row.genModels}
              />
            ))}
          </div>
        )}
      </SettingsBlock>
    </SettingsGroup>
  );
}
