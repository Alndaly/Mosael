import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type ProviderDefault = components["schemas"]["ProviderDefaultOut"];
type GenerationModel = components["schemas"]["GenerationModelOut"];

const NONE = "__none__";

function uniqueNonEmpty(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  values.forEach((value) => {
    const trimmed = value?.trim();
    if (!trimmed || seen.has(trimmed)) return;
    seen.add(trimmed);
    out.push(trimmed);
  });
  return out;
}

export function generationModelSuggestions(
  profile: ProviderProfile | null,
  genModels: GenerationModel[] | null,
  currentModel: string,
): string[] {
  const catalogModels = (genModels ?? [])
    .filter((item) => !profile || item.provider === profile.vendor)
    .map((item) => item.model);
  return uniqueNonEmpty([currentModel, profile?.default_model, ...catalogModels]);
}

/** 一行:某能力的默认供应商 + 模型。chat 的模型取自供应商 /models;image/video 允许自定义端点手填模型名。 */
function DefaultRow({
  capability,
  label,
  providers,
  current,
  genModels,
  highlighted,
}: {
  capability: string;
  label: string;
  providers: ProviderProfile[];
  current: ProviderDefault | undefined;
  genModels: GenerationModel[] | null;
  highlighted?: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const providerId = current?.provider_profile_id ?? "";
  const model = current?.model ?? "";
  const selectedProfile = providers.find((p) => p.id === providerId) ?? null;
  const isGenerationCapability = capability === "image" || capability === "video";

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
      : generationModelSuggestions(selectedProfile, genModels, model);
  const datalistId = `provider-default-model-options-${capability}`;

  const save = useMutation({
    mutationFn: (patch: { provider_profile_id: string | null; model: string }) =>
      api(`/api/settings/provider-defaults/${capability}`, { method: "PUT", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["provider-defaults"] }),
  });
  const [draftModel, setDraftModel] = React.useState(model);

  React.useEffect(() => {
    setDraftModel(model);
  }, [model, providerId]);

  const commitDraftModel = () => {
    const nextModel = draftModel.trim();
    if (nextModel === model) return;
    save.mutate({ provider_profile_id: providerId || null, model: nextModel });
  };

  return (
    <SettingsRow
      id={`provider-default-${capability}`}
      className={highlighted ? "provider-default-row is-highlighted" : "provider-default-row"}
      label={label}
    >
      <div className="provider-default-controls">
        <Select
          key={`p-${providerId || "none"}`}
          value={providerId || NONE}
          onValueChange={(value) => {
            const nextProviderId = value === NONE ? "" : value;
            const nextProfile = providers.find((profile) => profile.id === nextProviderId) ?? null;
            const nextModel = isGenerationCapability
              ? generationModelSuggestions(nextProfile, genModels, "")[0] ?? ""
              : "";
            save.mutate({ provider_profile_id: nextProviderId || null, model: nextModel });
          }}
        >
          <SelectTrigger className="provider-default-field">
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
        {isGenerationCapability ? (
          <>
            <Input
              className="provider-default-field"
              list={datalistId}
              value={draftModel}
              placeholder={!providerId ? t("providerDefaultsPickFirst") : t("providerDefaultsModelInputPlaceholder")}
              disabled={!providerId}
              onBlur={commitDraftModel}
              onChange={(event) => setDraftModel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.currentTarget.blur();
                }
              }}
            />
            <datalist id={datalistId}>
              {modelOptions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </>
        ) : (
          <Select
            key={`m-${model || "none"}`}
            value={model || NONE}
            onValueChange={(value) =>
              save.mutate({ provider_profile_id: providerId || null, model: value === NONE ? "" : value })
            }
            disabled={!providerId || modelOptions.length === 0}
          >
            <SelectTrigger className="provider-default-field">
              <SelectValue
                placeholder={
                  !providerId
                    ? t("providerDefaultsPickFirst")
                    : modelOptions.length === 0
                      ? t("providerDefaultsNoModels")
                      : t("agentModelPlaceholder")
                }
              />
            </SelectTrigger>
            <SelectContent>
              {modelOptions.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
    </SettingsRow>
  );
}

export function ProviderDefaultsSection({ focusCapability }: { focusCapability?: string | null }) {
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

  React.useEffect(() => {
    if (!focusCapability) return;
    window.setTimeout(() => {
      document.getElementById(`provider-default-${focusCapability}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 80);
  }, [focusCapability]);

  return (
    <SettingsGroup title={t("providerDefaultsTitle")} description={t("providerDefaultsDesc")}>
      {enabled.length === 0 ? (
        <SettingsBlock>
          <p className="feishu-empty">{t("kbEmbedNoProvider")}</p>
        </SettingsBlock>
      ) : (
        <>
          {rows.map((row) => (
            <DefaultRow
              key={row.capability}
              capability={row.capability}
              label={row.label}
              providers={enabled}
              current={byCapability.get(row.capability)}
              genModels={row.genModels}
              highlighted={focusCapability === row.capability}
            />
          ))}
        </>
      )}
    </SettingsGroup>
  );
}
