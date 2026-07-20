import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ExternalLink, KeyRound, Pencil, Plus, Power, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/ui/modals";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];
type ProfileForm = {
  vendor: string;
  name: string;
  api_key: string;
  base_url: string;
  default_model: string;
  /** Vendor-specific credentials, keyed by the preset's field spec. 火山 needs three of these
      across its two vendors, and they are not interchangeable. */
  extra: Record<string, string>;
};

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
  const EMPTY: ProfileForm = { vendor: "moonshot", name: "", api_key: "", base_url: "", default_model: "", extra: {} };

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const vendors = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<VendorPreset[]>("/api/settings/provider-vendors"),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["provider-profiles"] });

  const schema = React.useMemo(() => {
    const base = z.object({
      vendor: z.string(),
      name: z.string().trim().min(1, t("fieldRequired")),
      api_key: z.string(),
      base_url: z.string(),
      default_model: z.string(),
      extra: z.record(z.string(), z.string()),
    });
    // API key required when creating; on edit a blank key means "keep existing".
    return editing
      ? base
      : base.refine((data) => data.api_key.trim().length > 0, { message: t("fieldRequired"), path: ["api_key"] });
  }, [editing, t]);
  const form = useForm<ProfileForm>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const vendor = form.watch("vendor");

  const closeModal = () => {
    setAdding(false);
    setEditing(null);
    form.reset(EMPTY);
  };
  const openCreate = () => {
    setEditing(null);
    form.reset(EMPTY);
    setAdding(true);
  };
  const openEdit = (profile: ProviderProfile) => {
    setAdding(false);
    setEditing(profile);
    // 密钥只存掩码,留空表示保持不变
    form.reset({
      vendor: profile.vendor,
      name: profile.name,
      api_key: "",
      base_url: profile.base_url,
      default_model: profile.default_model,
      // Secret extras come back only as "…abcd", so prefilling one would submit the mask as
      // the new value. Blank means "keep", exactly like api_key above.
      extra: Object.fromEntries(
        (vendors.data?.find((item) => item.vendor === profile.vendor)?.fields ?? []).map((spec) => [
          spec.key,
          spec.secret ? "" : (profile.extra ?? {})[spec.key] ?? "",
        ]),
      ),
    });
  };

  const create = useMutation({
    mutationFn: (values: ProfileForm) =>
      api<ProviderProfile>("/api/settings/providers", {
        method: "POST",
        body: JSON.stringify({
          name: values.name.trim(),
          vendor: values.vendor,
          api_key: values.api_key.trim(),
          base_url: values.base_url.trim(),
          default_model: values.default_model.trim(),
          extra: values.extra,
        }),
      }),
    onSuccess: () => {
      closeModal();
      void refresh();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, values }: { id: string; values: ProfileForm }) =>
      api<ProviderProfile>(`/api/settings/providers/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: values.name.trim(),
          base_url: values.base_url.trim(),
          default_model: values.default_model.trim(),
          // 只有真正输入了新 key 才提交,否则后端保持原值
          ...(values.api_key.trim() ? { api_key: values.api_key.trim() } : {}),
          // extra 由后端按字段是否 secret 合并:密钥留空=保持,可见标识留空=清除
          extra: values.extra,
        }),
      }),
    onSuccess: () => {
      closeModal();
      void refresh();
    },
  });
  const submit = form.handleSubmit((values) => {
    if (editing) update.mutate({ id: editing.id, values });
    else create.mutate(values);
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
        <Form {...form}>
          <form className="task-create-form" onSubmit={submit} noValidate>
            <FormField
              control={form.control}
              name="vendor"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("providerVendorLabel")}</FormLabel>
                  {editing ? (
                    // 供应商类型是解析主键、编辑时不可改;只读显示,避免非预设 vendor 的空下拉
                    <Input value={vendorLabel(field.value)} disabled readOnly />
                  ) : (
                    <FormControl>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(vendors.data ?? []).map((item) => (
                            <SelectItem key={item.vendor} value={item.vendor}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormControl>
                  )}
                  {preset?.capabilities && (
                    <FormDescription className="provider-caps">{preset.capabilities}</FormDescription>
                  )}
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("providerNameLabel")}</FormLabel>
                  <FormControl>
                    <Input placeholder={t("providerName")} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="api_key"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="provider-key-label">
                    API Key
                    {docsUrl && (
                      <a className="provider-hint-link" href={docsUrl} target="_blank" rel="noreferrer noopener">
                        {t("providerGetKey")}
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      placeholder={editing ? t("providerKeyKeepPlaceholder") : t("providerKeyPlaceholder")}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {(preset?.fields ?? []).map((spec) => (
              <FormField
                key={spec.key}
                control={form.control}
                name={`extra.${spec.key}` as const}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{spec.label}</FormLabel>
                    <FormControl>
                      <Input
                        type={spec.secret ? "password" : "text"}
                        placeholder={spec.secret && editing ? t("providerKeyKeepPlaceholder") : ""}
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    {spec.hint && <FormDescription>{spec.hint}</FormDescription>}
                  </FormItem>
                )}
              />
            ))}
            <FormField
              control={form.control}
              name="base_url"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Base URL</FormLabel>
                  <FormControl>
                    <Input placeholder={preset?.base_url || t("providerBaseUrl")} {...field} />
                  </FormControl>
                  <FormDescription>
                    {preset?.base_url
                      ? t("providerBaseUrlDefault").replace("{url}", preset.base_url)
                      : t("providerBaseUrlRequired")}
                  </FormDescription>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="default_model"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("providerModelLabel")}</FormLabel>
                  <FormControl>
                    <Input placeholder={t("providerModel")} {...field} />
                  </FormControl>
                  {preset?.default_model && (
                    <FormDescription>{t("providerModelExample").replace("{model}", preset.default_model)}</FormDescription>
                  )}
                </FormItem>
              )}
            />
            <div className="task-create-actions">
              <Button type="button" variant="outline" size="sm" onClick={closeModal}>
                {t("cancel")}
              </Button>
              <Button type="submit" size="sm" disabled={editing ? update.isPending : create.isPending}>
                {editing ? (
                  t("save")
                ) : (
                  <>
                    <Plus size={13} /> {t("providerAdd")}
                  </>
                )}
              </Button>
            </div>
          </form>
        </Form>
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
