import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type ProviderDefault = components["schemas"]["ProviderDefaultOut"];

const NONE = "__none__";
/** 这一页**默认展示**哪几个能力分区 —— 不是"系统里有哪些能力"(那份由后端预设给),
 *  也不是"哪些能力能设默认模型"(后端 DEFAULTABLE_CAPABILITIES)。三者名字曾经长得一模一样,
 *  照着错的那份抄过一次(模型设置弹窗漏了 embedding)。 */
const SECTIONS_SHOWN_BY_DEFAULT = ["chat", "image", "video"] as const;

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

type CapabilityModel = components["schemas"]["CapabilityModelOut"];

/**
 * 一行:某能力的默认模型。
 *
 * **一个下拉,不是两个**。此前是"先选供应商再选模型" —— 那是模型还不是实体时的形状,逼着
 * 用户先知道"这个模型在哪条连接下",而那恰恰是他不关心的。现在模型自带能力与连接,直接列
 * 跨连接的候选即可,选项文本里带上连接名用来消歧(同名模型可能出现在两条连接下)。
 *
 * 想用列表里没有的模型,去那条连接的模型列表里加一行 —— 加进去的模型才有启用状态、上下文
 * 长度、推理/视觉这些设置。在这里直接手打一个名字会绕过全部这些,等于又造一个没有实体的模型。
 */
function DefaultRow({
  capability,
  label,
  current,
  highlighted,
}: {
  capability: string;
  label: string;
  current: ProviderDefault | undefined;
  highlighted?: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const providerId = current?.provider_profile_id ?? "";
  const model = current?.model ?? "";

  const candidates = useQuery({
    queryKey: ["capability-models", capability],
    queryFn: () => api<CapabilityModel[]>(`/api/settings/capability-models/${capability}`),
    staleTime: 30_000,
  });
  const options = candidates.data ?? [];
  // 值必须同时含连接与模型:同一个模型 id 可能出现在两条连接下(同一端点配了两把 key)。
  const valueOf = (item: CapabilityModel) => `${item.provider_profile_id}::${item.model}`;
  const currentValue = providerId && model ? `${providerId}::${model}` : NONE;

  const save = useMutation({
    mutationFn: (patch: { provider_profile_id: string | null; model: string }) =>
      api(`/api/settings/provider-defaults/${capability}`, { method: "PUT", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["provider-defaults"] }),
  });

  return (
    <SettingsRow
      id={`provider-default-${capability}`}
      className={cn(
        "grid-cols-[140px_minmax(0,1fr)] py-2.5 transition-[background,box-shadow] duration-[160ms]",
        highlighted && "bg-[color-mix(in_srgb,var(--primary)_3%,transparent)] shadow-[inset_2px_0_0_color-mix(in_srgb,var(--primary)_72%,transparent)]",
      )}
      controlClassName="w-full min-w-0 shrink"
      label={label}
    >
      <Select
        key={currentValue}
        value={currentValue}
        onValueChange={(value) => {
          if (value === NONE) {
            save.mutate({ provider_profile_id: null, model: "" });
            return;
          }
          const [nextProvider, ...rest] = value.split("::");
          save.mutate({ provider_profile_id: nextProvider, model: rest.join("::") });
        }}
      >
        <SelectTrigger className="h-8 w-full min-w-0">
          <SelectValue
            placeholder={options.length === 0 ? t("providerDefaultsNoModels") : t("agentModelPlaceholder")}
          />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>—</SelectItem>
          {options.map((item) => (
            <SelectItem key={valueOf(item)} value={valueOf(item)}>
              {item.provider_name} · {item.display_name || item.model}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingsRow>
  );
}

export function ProviderDefaultsSection({
  capabilities,
  focusCapability,
}: {
  capabilities?: string[];
  focusCapability?: string | null;
}) {
  const t = useI18n();
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
  });

  const enabled = (providers.data ?? []).filter((profile) => profile.enabled);
  const byCapability = new Map((defaults.data ?? []).map((row) => [row.capability, row]));
  const allRows: Array<{ capability: string; label: string }> = [
    { capability: "chat", label: t("capChat")},
    { capability: "image", label: t("capImage")},
    { capability: "video", label: t("capVideo")},
  ];
  const wanted = new Set(capabilities ?? SECTIONS_SHOWN_BY_DEFAULT);
  const rows = allRows.filter((row) => wanted.has(row.capability));

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
          <p className="m-0 text-xs text-muted-foreground">{t("kbEmbedNoProvider")}</p>
        </SettingsBlock>
      ) : (
        <>
          {rows.map((row) => (
            <DefaultRow
              key={row.capability}
              capability={row.capability}
              label={row.label}
              current={byCapability.get(row.capability)}
              highlighted={focusCapability === row.capability}
            />
          ))}
        </>
      )}
    </SettingsGroup>
  );
}
