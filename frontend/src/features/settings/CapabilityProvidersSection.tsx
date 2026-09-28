/**
 * 「能力提供方」(ADR 0031 §5):宿主的几项能力各用哪一家 —— 素材外链(本地素材传到哪一家对象存储换直链)、
 * 文档解析(本地解析还是 MinerU……)。一项能力一组,照后端的能力表列(GET /api/settings/capabilities)。
 *
 * **放在设置里,不放在插件页。** 它是一个跨插件的个人选择(几家里用哪一家),和默认模型同类;放在每一家连接上
 * 是几个互相牵制的开关 —— 打开一家会悄悄关掉另一家,想知道现在用的是哪家还得挨个点开看。挑法见
 * backend/app/domain/capabilities。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listCapabilityChoices, setCapabilityDefault, type CapabilityChoices as Choices } from "@/api/domains/capabilities";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { OptionPicker } from "@/components/ui/option-picker";
import { SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";

const UNSET = "__unset__";
const KEY = ["capability-providers"] as const;

/** 一家都没有时怎么说:素材外链要去建一个对象存储连接;别的能力说句通用的。 */
const NONE_HINT: Record<string, MessageKey> = { public_url: "assetLinkNone" };

export function CapabilityProvidersSection() {
  const state = useQuery({ queryKey: KEY, queryFn: listCapabilityChoices });
  return <>{(state.data ?? []).map((choices) => <CapabilityGroup key={choices.capability} choices={choices} />)}</>;
}

function CapabilityGroup({ choices }: { choices: Choices }) {
  const t = useI18n();
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (providerId: string | null) => setCapabilityDefault(choices.capability, providerId),
    onSuccess: (next) => qc.setQueryData<Choices[]>(KEY, (list) => (list ?? []).map((one) => (one.capability === next.capability ? next : one))),
  });

  const options = choices.options ?? [];
  const builtin = options.find((option) => option.builtin);
  const plugins = options.filter((option) => !option.builtin);
  const ready = plugins.filter((option) => (option.missing ?? []).length === 0);
  const unready = plugins.filter((option) => (option.missing ?? []).length > 0);

  //: 有内置实现的:不定就是内置的,它本身就是一项(选它 = 清掉默认)。没有的:「不指定」这一项说的是**不指定时会怎样**,
  //: 只取决于配好了哪几家 —— 和现在选没选无关。
  const automatic = options.find((option) => option.id === choices.automatic);
  const unsetLabel = builtin
    ? builtin.name
    : plugins.length === 0
      ? t(NONE_HINT[choices.capability] ?? "capabilityNone")
      : ready.length === 0
        ? t("assetLinkNoneReady")
        : automatic
          ? t("assetLinkAuto").replace("{name}", automatic.name)
          : t("assetLinkAsk");

  return (
    <SettingsGroup title={choices.label} description={toPlainText(choices.description)}>
      <SettingsRow
        label={t("capabilityProvider")}
        //: 没配好的不进下拉(选了也用不了),但要在这里说清缺什么 —— 否则用户不知道它为什么不在。
        description={
          unready.length
            ? unready.map((option) => t("assetLinkMissing").replace("{name}", option.name).replace("{fields}", (option.missing ?? []).join(t("listSeparator")))).join(" ")
            : undefined
        }
        controlClassName="w-full min-w-0 shrink"
        className="grid-cols-[140px_minmax(0,1fr)]"
      >
        <OptionPicker
          key={choices.current ?? UNSET}
          value={choices.current ?? UNSET}
          disabled={(!builtin && ready.length === 0) || save.isPending}
          onChange={(value) => save.mutate(value === UNSET ? null : value)}
          options={[
            { value: UNSET, label: unsetLabel },
            ...ready.map((option) => ({ value: option.id, label: option.name })),
          ]}
          className="w-full min-w-0"
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
