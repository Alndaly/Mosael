import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound, Pencil, Plus, Power, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/ui/modals";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];

/** 各供应商创建密钥的官方控制台入口(告知用户"去哪拿 key")。外链走系统浏览器。 */
const VENDOR_DOCS: Record<string, string> = {
  alibaba: "https://bailian.console.aliyun.com/?tab=model#/api-key",
  bytedance: "https://console.volcengine.com/ark",
  moonshot: "https://platform.moonshot.cn/console/api-keys",
  minimax: "https://platform.minimaxi.com/user-center/basic-information/interface-key",
  openai: "https://platform.openai.com/api-keys",
  google: "https://aistudio.google.com/app/apikey",
  kuaishou: "https://klingai.com/",
};

export function ProviderProfilesSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<ProviderProfile | null>(null);
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

  const resetForm = () => {
    setName("");
    setApiKey("");
    setBaseUrl("");
    setModel("");
  };
  const closeModal = () => {
    setAdding(false);
    setEditing(null);
    resetForm();
  };
  const openCreate = () => {
    setEditing(null);
    resetForm();
    setVendor("moonshot");
    setAdding(true);
  };
  const openEdit = (profile: ProviderProfile) => {
    setAdding(false);
    setEditing(profile);
    setName(profile.name);
    setVendor(profile.vendor);
    setApiKey(""); // 密钥只存掩码,留空表示保持不变
    setBaseUrl(profile.base_url);
    setModel(profile.default_model);
  };

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
      closeModal();
      void refresh();
    },
  });
  const update = useMutation({
    mutationFn: (id: string) =>
      api<ProviderProfile>(`/api/settings/providers/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          base_url: baseUrl.trim(),
          default_model: model.trim(),
          // 只有真正输入了新 key 才提交,否则后端保持原值
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        }),
      }),
    onSuccess: () => {
      closeModal();
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
  const preset = (vendors.data ?? []).find((item) => item.vendor === vendor) ?? null;
  const docsUrl = VENDOR_DOCS[vendor];

  return (
    <SettingsGroup
      title={t("settingsProviders")}
      description={t("providerSectionDesc")}
      actions={
        <Button variant="outline" size="sm" onClick={openCreate}>
          <Plus size={13} /> {t("providerAdd")}
        </Button>
      }
    >
      <ModalShell
        open={adding || editing !== null}
        onOpenChange={(next) => !next && closeModal()}
        title={editing ? t("providerEdit") : t("providerAdd")}
      >
        <form
          className="task-create-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (editing) {
              if (name.trim()) update.mutate(editing.id);
            } else if (name.trim() && apiKey.trim()) {
              create.mutate();
            }
          }}
        >
          <label className="wf-field">
            <span>{t("providerVendorLabel")}</span>
            {editing ? (
              // 供应商类型是解析主键、编辑时不可改;直接只读显示,避免非预设 vendor 的空下拉
              <Input value={vendorLabel(vendor)} disabled readOnly />
            ) : (
              <Select value={vendor} onValueChange={setVendor}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(vendors.data ?? []).map((preset) => (
                    <SelectItem key={preset.vendor} value={preset.vendor}>
                      {preset.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {preset?.capabilities && <small className="provider-caps">{preset.capabilities}</small>}
          </label>
          <label className="wf-field">
            <span>{t("providerNameLabel")}</span>
            <Input placeholder={t("providerName")} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="wf-field">
            <span>
              API Key
              {docsUrl && (
                <a className="provider-hint-link" href={docsUrl} target="_blank" rel="noreferrer noopener">
                  {t("providerGetKey")}
                  <ExternalLink size={11} />
                </a>
              )}
            </span>
            <Input
              type="password"
              placeholder={editing ? t("providerKeyKeepPlaceholder") : t("providerKeyPlaceholder")}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <label className="wf-field">
            <span>Base URL</span>
            <Input
              placeholder={preset?.base_url || t("providerBaseUrl")}
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
            <small>
              {preset?.base_url
                ? t("providerBaseUrlDefault").replace("{url}", preset.base_url)
                : t("providerBaseUrlRequired")}
            </small>
          </label>
          <label className="wf-field">
            <span>{t("providerModelLabel")}</span>
            <Input placeholder={t("providerModel")} value={model} onChange={(event) => setModel(event.target.value)} />
            {preset?.default_model && (
              <small>{t("providerModelExample").replace("{model}", preset.default_model)}</small>
            )}
          </label>
          <div className="task-create-actions">
            <Button type="button" variant="outline" size="sm" onClick={closeModal}>
              {t("cancel")}
            </Button>
            {editing ? (
              <Button type="submit" size="sm" disabled={!name.trim() || update.isPending}>
                {t("save")}
              </Button>
            ) : (
              <Button type="submit" size="sm" disabled={!name.trim() || !apiKey.trim() || create.isPending}>
                <Plus size={13} /> {t("providerAdd")}
              </Button>
            )}
          </div>
        </form>
      </ModalShell>

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
                <Button variant="ghost" size="icon-sm" onClick={() => openEdit(profile)} aria-label={t("providerEdit")}>
                  <Pencil size={13} />
                </Button>
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
