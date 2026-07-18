import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type EmbeddingConfig = components["schemas"]["KbEmbeddingConfigOut"];

export function KbEmbeddingSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const [providerId, setProviderId] = React.useState("");
  const [model, setModel] = React.useState("");
  const [dim, setDim] = React.useState(768);
  const [initialDim, setInitialDim] = React.useState(768);

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const config = useQuery({
    queryKey: ["kb-embedding"],
    queryFn: () => api<EmbeddingConfig>("/api/settings/kb-embedding"),
  });

  // 配置载入后回填一次表单
  React.useEffect(() => {
    if (!config.data) return;
    setProviderId(config.data.provider_profile_id ?? "");
    setModel(config.data.model);
    setDim(config.data.dim || 768);
    setInitialDim(config.data.dim || 768);
  }, [config.data]);

  const save = useMutation({
    mutationFn: () =>
      api<EmbeddingConfig>("/api/settings/kb-embedding", {
        method: "PUT",
        body: JSON.stringify({
          provider_profile_id: providerId || null,
          model: model.trim(),
          dim,
        }),
      }),
    onSuccess: () => {
      setInitialDim(dim);
      void qc.invalidateQueries({ queryKey: ["kb-embedding"] });
      void qc.invalidateQueries({ queryKey: ["kb-status"] });
    },
  });

  const enabledProfiles = (profiles.data ?? []).filter((profile) => profile.enabled);
  const dimChanged = dim !== initialDim;
  // 两个查询都就绪再挂表单:否则 Radix Select 会在选项挂载前拿到 value,显示空占位。
  const ready = profiles.data !== undefined && config.data !== undefined;

  return (
    <SettingsGroup title={t("kbEmbedTitle")} description={t("kbEmbedDesc")}>
      <SettingsBlock>
        {!ready ? null : enabledProfiles.length === 0 ? (
          <p className="feishu-empty">{t("kbEmbedNoProvider")}</p>
        ) : (
          <form
            className="task-create-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (model.trim() && dim > 0) save.mutate();
            }}
          >
            <label className="wf-field">
              <span>{t("kbEmbedProvider")}</span>
              {/* key 随 value 变化强制重挂,规避 Radix 对「初始受控值」不刷新显示文本的问题 */}
              <Select key={providerId || "none"} value={providerId} onValueChange={setProviderId}>
                <SelectTrigger>
                  <SelectValue placeholder={t("kbEmbedPickProvider")} />
                </SelectTrigger>
                <SelectContent>
                  {enabledProfiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="wf-field">
              <span>{t("kbEmbedModel")}</span>
              <Input
                placeholder={t("kbEmbedModelPlaceholder")}
                value={model}
                onChange={(event) => setModel(event.target.value)}
              />
            </label>
            <label className="wf-field">
              <span>{t("kbEmbedDim")}</span>
              <Input
                type="number"
                min={1}
                value={dim}
                onChange={(event) => setDim(Number(event.target.value) || 0)}
              />
              {dimChanged && (
                <small className="kb-embed-warn">
                  <AlertTriangle size={12} /> {t("kbEmbedDimWarn")}
                </small>
              )}
            </label>
            <div className="task-create-actions">
              <small className="kb-embed-note">{t("kbEmbedRebuildNote")}</small>
              <Button type="submit" size="sm" disabled={!model.trim() || dim <= 0 || save.isPending}>
                {t("save")}
              </Button>
            </div>
          </form>
        )}
      </SettingsBlock>
    </SettingsGroup>
  );
}
