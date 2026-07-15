import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Power, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];

export function ProviderProfilesSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [name, setName] = React.useState("");
  const [vendor, setVendor] = React.useState("moonshot");
  const [apiKey, setApiKey] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [model, setModel] = React.useState("");

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const vendors = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<VendorPreset[]>("/api/settings/provider-vendors"),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["provider-profiles"] });

  const create = useMutation({
    mutationFn: () =>
      api<ProviderProfile>("/api/settings/providers", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          vendor,
          api_key: apiKey.trim(),
          base_url: baseUrl.trim(),
          default_model: model.trim(),
        }),
      }),
    onSuccess: () => {
      setAdding(false);
      setName("");
      setApiKey("");
      setBaseUrl("");
      setModel("");
      void refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (profile: ProviderProfile) =>
      api<ProviderProfile>(`/api/settings/providers/${profile.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !profile.enabled }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/settings/providers/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  const vendorLabel = (value: string) => (vendors.data ?? []).find((item) => item.vendor === value)?.label ?? value;

  return (
    <SettingsGroup
      title={t("settingsProviders")}
      description={t("providerSectionDesc")}
      actions={
        <Button variant="outline" size="sm" onClick={() => setAdding((value) => !value)}>
          <Plus size={13} /> {t("providerAdd")}
        </Button>
      }
    >
      {adding && (
        <SettingsBlock>
          <form
            className="provider-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && apiKey.trim()) create.mutate();
            }}
          >
            <select value={vendor} onChange={(event) => setVendor(event.target.value)}>
              {(vendors.data ?? []).map((preset) => (
                <option key={preset.vendor} value={preset.vendor}>
                  {preset.label}
                </option>
              ))}
            </select>
            <Input placeholder={t("providerName")} value={name} onChange={(event) => setName(event.target.value)} />
            <Input
              type="password"
              placeholder={t("providerKeyPlaceholder")}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
            <Input
              placeholder={t("providerBaseUrl")}
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
            <Input placeholder={t("providerModel")} value={model} onChange={(event) => setModel(event.target.value)} />
            <Button type="submit" size="sm" disabled={!name.trim() || !apiKey.trim() || create.isPending}>
              {t("save")}
            </Button>
          </form>
        </SettingsBlock>
      )}

      <SettingsBlock>
        <div className="provider-list">
          {(profiles.data ?? []).map((profile) => (
            <div className={profile.enabled ? "provider-row" : "provider-row disabled"} key={profile.id}>
              <span className="feishu-bot-icon">
                <KeyRound size={13} />
              </span>
              <div className="feishu-bot-body">
                <strong>{profile.name}</strong>
                <small>
                  {vendorLabel(profile.vendor)} · {profile.key_hint}
                  {profile.default_model ? ` · ${profile.default_model}` : ""}
                  {profile.base_url ? ` · ${profile.base_url}` : ""}
                </small>
              </div>
              {!profile.enabled && <Badge variant="outline">{t("providerDisabled")}</Badge>}
              <div className="feishu-bot-actions">
                <Button variant="ghost" size="icon-sm" onClick={() => toggle.mutate(profile)} aria-label="toggle">
                  <Power size={13} />
                </Button>
                <Button variant="ghost" size="icon-sm" onClick={() => remove.mutate(profile.id)} aria-label={t("delete")}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          ))}
          {profiles.data?.length === 0 && <p className="feishu-empty">{t("providerNoProfiles")}</p>}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
