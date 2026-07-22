import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertTriangle } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type EmbeddingConfig = components["schemas"]["KbEmbeddingConfigOut"];
type EmbForm = { provider_profile_id: string; model: string; dim: number };

function normalize(values: EmbForm): EmbForm {
  return {
    provider_profile_id: values.provider_profile_id || "",
    model: values.model.trim(),
    dim: Number(values.dim) || 0,
  };
}

function sameConfig(a: EmbForm | null, b: EmbForm): boolean {
  return Boolean(a && a.provider_profile_id === b.provider_profile_id && a.model === b.model && a.dim === b.dim);
}

export function KbEmbeddingSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const [initialDim, setInitialDim] = React.useState(768);
  const lastSavedRef = React.useRef<EmbForm | null>(null);

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const config = useQuery({
    queryKey: ["kb-embedding"],
    queryFn: () => api<EmbeddingConfig>("/api/settings/kb-embedding"),
  });

  const form = useForm<EmbForm>({
    resolver: zodResolver(
      z.object({
        provider_profile_id: z.string(),
        model: z.string().trim().min(1, t("fieldRequired")),
        dim: z.number().min(1, t("fieldRequired")),
      }),
    ),
    defaultValues: { provider_profile_id: "", model: "", dim: 768 },
  });

  // 配置载入后回填一次表单
  React.useEffect(() => {
    if (!config.data) return;
    const next = {
      provider_profile_id: config.data.provider_profile_id ?? "",
      model: config.data.model,
      dim: config.data.dim || 768,
    };
    lastSavedRef.current = normalize(next);
    form.reset(next);
    setInitialDim(config.data.dim || 768);
  }, [config.data]);

  const save = useMutation({
    mutationFn: (values: EmbForm) =>
      api<EmbeddingConfig>("/api/settings/kb-embedding", {
        method: "PUT",
        body: JSON.stringify({
          provider_profile_id: values.provider_profile_id || null,
          model: values.model.trim(),
          dim: values.dim,
        }),
      }),
    onSuccess: (_data, values) => {
      const saved = normalize(values);
      lastSavedRef.current = saved;
      setInitialDim(saved.dim);
      void qc.invalidateQueries({ queryKey: ["kb-embedding"] });
      void qc.invalidateQueries({ queryKey: ["kb-status"] });
    },
  });

  const enabledProfiles = (profiles.data ?? []).filter(
    (profile) => profile.enabled && (profile.capability_ids ?? []).includes("embedding"),
  );
  const watched = useWatch({ control: form.control });
  const dimChanged = (watched.dim ?? 0) !== initialDim;
  // 两个查询都就绪再挂表单:否则 Radix Select 会在选项挂载前拿到 value,显示空占位。
  const ready = profiles.data !== undefined && config.data !== undefined;

  React.useEffect(() => {
    if (!ready || enabledProfiles.length === 0) return;
    const next = normalize({
      provider_profile_id: watched.provider_profile_id ?? "",
      model: watched.model ?? "",
      dim: watched.dim ?? 0,
    });
    if (!next.model || next.dim < 1 || sameConfig(lastSavedRef.current, next)) return;
    const timer = window.setTimeout(() => save.mutate(next), 600);
    return () => window.clearTimeout(timer);
  }, [ready, enabledProfiles.length, watched.provider_profile_id, watched.model, watched.dim]);

  return (
    <SettingsGroup title={t("kbEmbedTitle")} description={t("kbEmbedDesc")}>
      <SettingsBlock>
        {!ready ? null : enabledProfiles.length === 0 ? (
          <p className="m-0 text-xs text-muted-foreground">{t("kbEmbedNoProvider")}</p>
        ) : (
          <Form {...form}>
            <div className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
              <FormField
                control={form.control}
                name="provider_profile_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("kbEmbedProvider")}</FormLabel>
                    <FormControl>
                      {/* key 随 value 变化强制重挂,规避 Radix 初始受控值不刷新显示文本 */}
                      <Select key={field.value || "none"} value={field.value} onValueChange={field.onChange}>
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
                    </FormControl>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="model"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("kbEmbedModel")}</FormLabel>
                    <FormControl>
                      <Input placeholder={t("kbEmbedModelPlaceholder")} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="dim"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("kbEmbedDim")}</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        value={field.value}
                        onChange={(event) => field.onChange(Number(event.target.value) || 0)}
                      />
                    </FormControl>
                    {dimChanged ? (
                      <small className="mt-1 inline-flex items-center gap-1 text-[color:var(--warning,#b45309)]">
                        <AlertTriangle size={12} /> {t("kbEmbedDimWarn")}
                      </small>
                    ) : (
                      <FormMessage />
                    )}
                  </FormItem>
                )}
              />
              <div className="mt-1 flex justify-end gap-1.5">
                <small className="flex-1 self-center text-muted-foreground">{t("kbEmbedRebuildNote")}</small>
                <small className="self-center whitespace-nowrap text-[11.5px] text-muted-foreground">{save.isPending ? t("wfSaving") : t("wfSavedShort")}</small>
              </div>
            </div>
          </Form>
        )}
      </SettingsBlock>
    </SettingsGroup>
  );
}
