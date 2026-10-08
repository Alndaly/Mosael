import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listCapabilityModels,
  listProviderDefaults,
  listProviderProfiles,
  setProviderDefault,
  type CapabilityModel,
  type ProviderDefault,
  type ProviderProfile,
} from "@/api/client";
import { providerKeys, generationKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";
import { formedGroups, generationPickerEntry } from "@/lib/entryNames";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { PROVIDER_FIX_ATTR, providerProblem, providerRowId, type ProviderProblem } from "./providerProblem";

const PROBLEM_TEXT: Record<ProviderProblem, "providerDefaultBroken_disabled" | "providerDefaultBroken_unauthorized" | "providerDefaultBroken_expired" | "providerDefaultBroken_noKey"> = {
  disabled: "providerDefaultBroken_disabled",
  unauthorized: "providerDefaultBroken_unauthorized",
  expired: "providerDefaultBroken_expired",
  noKey: "providerDefaultBroken_noKey",
};

/** 「去处理」:滚到那条连接、把焦点交给它那颗修它的按钮(授权 / 填密钥);停用的交给那一行本身。 */
function goFixConnection(profileId: string) {
  const row = document.getElementById(providerRowId(profileId));
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  (row.querySelector<HTMLElement>(`[${PROVIDER_FIX_ATTR}]`) ?? row).focus({ preventScroll: true });
}


const NONE = "__none__";
/** 这一页**默认展示**哪几个能力分区 —— 不是"系统里有哪些能力"(那份由后端预设给),
 *  也不是"哪些能力能设默认模型"(后端 DEFAULTABLE_CAPABILITIES)。三者名字曾经长得一模一样,
 *  照着错的那份抄过一次(模型设置弹窗漏了 embedding)。 */
const SECTIONS_SHOWN_BY_DEFAULT = ["chat", "image", "video"] as const;


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
  connection,
}: {
  capability: string;
  label: string;
  current: ProviderDefault | undefined;
  highlighted?: boolean;
  /** 默认模型所在的那条连接(没设默认就没有)。 */
  connection?: ProviderProfile;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const providerId = current?.provider_profile_id ?? "";
  const model = current?.model ?? "";

  const candidates = useQuery({
    queryKey: providerKeys.capabilityModels(capability),
    queryFn: () => listCapabilityModels(capability),
    staleTime: 30_000,
  });
  const options = candidates.data ?? [];
  const formed = formedGroups(options);
  // 值必须同时含连接与模型:同一个模型 id 可能出现在两条连接下(同一端点配了两把 key)。
  const valueOf = (item: CapabilityModel) => `${item.provider_profile_id}::${item.model}`;
  const currentValue = providerId && model ? `${providerId}::${model}` : NONE;
  const problem = connection && currentValue !== NONE ? providerProblem(connection) : null;

  const save = useMutation({
    mutationFn: (patch: { provider_profile_id: string | null; model: string }) =>
      setProviderDefault(capability, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: providerKeys.defaults() });
      // 生成选择器按 `is_default` 预选 —— 换了默认,那边要跟着换。
      void qc.invalidateQueries({ queryKey: generationKeys.options() });
    },
  });

  return (
    <SettingsRow
      id={`provider-default-${capability}`}
      className={cn(
        "grid-cols-[140px_minmax(0,1fr)] transition-[background,box-shadow] duration-[160ms]",
        highlighted && "bg-[color-mix(in_srgb,var(--primary)_3%,transparent)] shadow-[inset_2px_0_0_color-mix(in_srgb,var(--primary)_72%,transparent)]",
      )}
      controlClassName="w-full min-w-0 shrink"
      label={label}
    >
      <div className="grid min-w-0 gap-1.5">
      {/* 一条连接下几十个模型是常态,超过阈值 OptionPicker 自己换成可搜索的那一版。 */}
      <OptionPicker
        key={currentValue}
        value={currentValue}
        disabled={options.length === 0}
        onChange={(value) => {
          if (value === NONE) {
            save.mutate({ provider_profile_id: null, model: "" });
            return;
          }
          const [nextProvider, ...rest] = value.split("::");
          save.mutate({ provider_profile_id: nextProvider, model: rest.join("::") });
        }}
        options={[
          {
            value: NONE,
            /*
             * **不要用一条横线。** 这一格永远有值(没配就是 NONE),所以 placeholder 从来轮不上,
             * 用户看到的就是那条 `—` —— 它既没说"这里还没配",也没说"选它会怎样",读起来像是
             * 这一行坏了。没有可用模型时更要说清:那不是"未设置",是"还没有东西可选"。
             */
            label: options.length === 0 ? t("providerDefaultsEmpty") : t("providerDefaultsUnset"),
            description: options.length === 0 ? undefined : t("providerDefaultsUnsetHint"),
          },
          //: 两层名字(ADR 0045):主名是这个模型自己的,第二行说它来自哪条连接;有表单的工作流的几个入口挨着、
          //: 各自一行(第二行写「完整工作流」/「来自 X」)。和 AI Studio、画板同一种样子;记得住原始 model id 的人仍然搜得到。
          ...options.map((item) => ({
            value: valueOf(item),
            ...generationPickerEntry(
              { model: item.model, model_label: item.display_name || item.model, profile_name: item.provider_name, group: item.group },
              formed,
              t,
            ),
          })),
        ]}
        className="w-full min-w-0"
      />
      {/* 默认模型所在的连接现在用不了(未授权、没填密钥、停用):此前这一行毫无提示,AI Studio、智能体用默认模型时才报错,
          回到设置页也看不出默认模型就是坏的那条(体检 UM-23)。 */}
      {problem && connection && (
        <p data-default-broken={problem} className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-destructive">
          <span>{t(PROBLEM_TEXT[problem]).replace("{name}", connection.name)}</span>
          <Button variant="outline" size="xs" onClick={() => goFixConnection(connection.id)}>
            {t("providerDefaultFix")}
          </Button>
        </p>
      )}
      </div>
    </SettingsRow>
  );
}

export function ProviderDefaultsSection({
  capabilities,
  focusCapability,
  title,
  description,
}: {
  capabilities?: string[];
  focusCapability?: string | null;
  title?: string;
  description?: string;
}) {
  const t = useI18n();
  const providers = useQuery({
    queryKey: providerKeys.profiles(),
    queryFn: listProviderProfiles,
  });
  // 只有**我自己**那一份。曾经还有一份部署默认(管理页读 /api/admin/provider-defaults)——
  // 删掉了:一个我没选过的模型替我回答,花我的额度、用我的钥匙,而我从没同意过。
  const defaults = useQuery({
    queryKey: providerKeys.defaults(),
    queryFn: listProviderDefaults,
  });

  const byCapability = new Map((defaults.data ?? []).map((row) => [row.capability, row]));
  const allRows: Array<{ capability: string; label: string }> = [
    { capability: "chat", label: t("capChat")},
    { capability: "image", label: t("capImage")},
    { capability: "video", label: t("capVideo")},
    { capability: "audio", label: t("capAudio")},
  ];
  const wanted = new Set<string>(capabilities ?? SECTIONS_SHOWN_BY_DEFAULT);
  const rows = allRows.filter((row) => wanted.has(row.capability));
  //: 空态只看**这几种能力的**连接:图像页上有一条对话连接,不等于图像有东西可选。
  //: 「一条都没有」和「有、但都停用了」下一步不一样(添加 / 启用),分开说。
  const related = (providers.data ?? []).filter((profile) => (profile.capability_ids ?? []).some((one) => wanted.has(one)));
  const enabled = related.filter((profile) => profile.enabled);

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
    <SettingsGroup
      title={title ?? t("providerDefaultsTitle")}
      description={description ?? t("providerDefaultsDesc")}
    >
      {enabled.length === 0 ? (
        <SettingsBlock>
          <p className="m-0 text-xs text-muted-foreground">
            {related.length === 0 ? t("providerDefaultsNoProvider") : t("providerDefaultsAllDisabled")}
          </p>
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
              connection={(providers.data ?? []).find((profile) => profile.id === byCapability.get(row.capability)?.provider_profile_id)}
            />
          ))}
        </>
      )}
    </SettingsGroup>
  );
}
