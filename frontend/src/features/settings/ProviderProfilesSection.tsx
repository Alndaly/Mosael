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
import { ModalShell } from "@/components/app/modals";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];
type ProfileForm = {
  vendor: string;
  name: string;
  /** Adapter-specific settings, keyed by the backend preset's field spec. */
  config: Record<string, string>;
};

/** 各供应商创建密钥的官方控制台入口(告知用户"去哪拿 key")。外链走系统浏览器。 */
const VENDOR_DOCS: Record<string, string> = {
  alibaba: "https://bailian.console.aliyun.com/?tab=model#/api-key",
  bytedance: "https://console.volcengine.com/ark",
  moonshot: "https://platform.moonshot.cn/console/api-keys",
  minimax: "https://platform.minimaxi.com/user-center/basic-information/interface-key",
  openai: "https://platform.openai.com/api-keys",
  "openai-tts": "https://platform.openai.com/api-keys",
  google: "https://aistudio.google.com/app/apikey",
  kuaishou: "https://klingai.com/",
  "volcano-podcast": "https://console.volcengine.com/speech/service",
  volcano: "https://console.volcengine.com/speech/service",
};

function cleanConfig(config: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(config).map(([key, value]) => [key, (value ?? "").trim()]));
}

export function ProviderProfilesSection({
  capability,
  title,
  description,
}: {
  capability?: string | null;
  title?: string;
  description?: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<ProviderProfile | null>(null);
  const EMPTY: ProfileForm = { vendor: "moonshot", name: "", config: {} };

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
    return z
      .object({
        vendor: z.string(),
        name: z.string().trim().min(1, t("fieldRequired")),
        config: z.record(z.string(), z.string()),
      })
      .superRefine((data, ctx) => {
        const preset = (vendors.data ?? []).find((item) => item.vendor === data.vendor);
        for (const spec of preset?.fields ?? []) {
          if (!spec.required) continue;
          if (editing && spec.secret) continue;
          if ((data.config?.[spec.key] ?? "").trim()) continue;
          ctx.addIssue({ code: z.ZodIssueCode.custom, message: t("fieldRequired"), path: ["config", spec.key] });
        }
      });
  }, [editing, t, vendors.data]);
  const form = useForm<ProfileForm>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const vendor = form.watch("vendor");

  const vendorOptions = React.useMemo(() => {
    const items = vendors.data ?? [];
    return capability ? items.filter((item) => (item.capability_ids ?? []).includes(capability)) : items;
  }, [capability, vendors.data]);
  const visibleProfiles = React.useMemo(() => {
    const items = profiles.data ?? [];
    return capability ? items.filter((profile) => (profile.capability_ids ?? []).includes(capability)) : items;
  }, [capability, profiles.data]);
  const initialVendor = vendorOptions[0]?.vendor ?? "moonshot";

  React.useEffect(() => {
    if (!adding || editing || vendorOptions.some((item) => item.vendor === vendor)) return;
    form.setValue("vendor", initialVendor);
  }, [adding, editing, form, initialVendor, vendor, vendorOptions]);

  const closeModal = () => {
    setAdding(false);
    setEditing(null);
    form.reset({ ...EMPTY, vendor: initialVendor });
  };
  const openCreate = () => {
    setEditing(null);
    form.reset({ ...EMPTY, vendor: initialVendor });
    setAdding(true);
  };
  const openEdit = (profile: ProviderProfile) => {
    setAdding(false);
    setEditing(profile);
    // 密钥只存掩码,留空表示保持不变
    form.reset({
      vendor: profile.vendor,
      name: profile.name,
      // Secret fields come back only as "…abcd", so prefilling one would submit the mask as
      // the new value. Blank means "keep".
      config: Object.fromEntries(
        (vendors.data?.find((item) => item.vendor === profile.vendor)?.fields ?? []).map((spec) => [
          spec.key,
          spec.secret ? "" : (profile.config ?? {})[spec.key] ?? "",
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
          config: cleanConfig(values.config),
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
          config: cleanConfig(values.config),
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
      title={title ?? t("providerAccountsTitle")}
      description={description ?? t("providerAccountsDesc")}
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
          <form className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-secondary [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" onSubmit={submit} noValidate>
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
                          {vendorOptions.map((item) => (
                            <SelectItem key={item.vendor} value={item.vendor}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormControl>
                  )}
                  {preset?.capabilities && (
                    <FormDescription className="mt-0.5 leading-[1.4] text-muted-foreground">{preset.capabilities}</FormDescription>
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
            {(preset?.fields ?? []).map((spec) => (
              <FormField
                key={spec.key}
                control={form.control}
                name={`config.${spec.key}` as const}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="flex items-center gap-2">
                      {spec.label}
                      {spec.storage === "api_key" && docsUrl && (
                        <a className="ml-auto inline-flex items-center gap-[3px] text-[11px] font-medium text-primary no-underline hover:underline" href={docsUrl} target="_blank" rel="noreferrer noopener">
                          {t("providerGetKey")}
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </FormLabel>
                    <FormControl>
                      <Input
                        type={spec.secret ? "password" : "text"}
                        placeholder={spec.secret && editing ? t("providerKeyKeepPlaceholder") : spec.default || ""}
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    {(spec.hint || spec.default) && (
                      <FormDescription>
                        {spec.hint || t("providerFieldDefault").replace("{value}", spec.default)}
                      </FormDescription>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
            <div className="mt-1 flex justify-end gap-1.5">
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
        <div className="grid gap-1.5">
          {visibleProfiles.map((profile) => (
            <div className={cn("grid grid-cols-[28px_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md border border-border bg-panel px-2 py-1.5", !profile.enabled && "opacity-55")} key={profile.id}>
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
                <KeyRound size={13} />
              </span>
              <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[13px] [&_strong]:font-semibold">
                <strong>{profile.name}</strong>
                <small>
                  {vendorLabel(profile.vendor)} · {profile.key_hint}
                  {profile.default_model ? ` · ${profile.default_model}` : ""}
                  {profile.base_url ? ` · ${profile.base_url}` : ""}
                </small>
              </div>
              {!profile.enabled && <Badge variant="outline">{t("providerDisabled")}</Badge>}
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" onClick={() => openEdit(profile)} aria-label={t("providerEdit")}>
                  <Pencil size={13} />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => toggle.mutate(profile)} aria-label="toggle">
                  <Power size={13} />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => remove.mutate(profile.id)} aria-label={t("delete")}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          ))}
          {profiles.data && visibleProfiles.length === 0 && (
            <p className="m-0 text-xs text-muted-foreground">{capability ? t("providerNoCapabilityProfiles") : t("providerNoProfiles")}</p>
          )}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
