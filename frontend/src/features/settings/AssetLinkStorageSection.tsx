/**
 * 「素材外链」:生成模型只收链接时(方舟 Seedance 的参考视频),本地素材传到哪一家对象存储。
 *
 * **放在设置里,不放在插件页。** 它是一个跨插件的个人选择(几家里用哪一家),和默认模型同类;
 * 放在每一家连接上是几个互相牵制的开关 —— 打开一家会悄悄关掉另一家,想知道现在用的是哪家还得
 * 挨个点开看。后端的选择规则见 backend/app/domain/generation/public_links.py。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";

type State = components["schemas"]["AssetLinkStorageOut"];

const UNSET = "__unset__";
const KEY = ["asset-link-storage"] as const;

export function AssetLinkStorageSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const state = useQuery({ queryKey: KEY, queryFn: () => api<State>("/api/settings/asset-link-storage") });
  const save = useMutation({
    mutationFn: (instanceId: string | null) =>
      api<State>("/api/settings/asset-link-storage", { method: "PUT", body: JSON.stringify({ instance_id: instanceId }) }),
    onSuccess: (next) => qc.setQueryData(KEY, next),
  });

  const options = state.data?.options ?? [];
  const automatic = options.find((option) => option.instance_id === state.data?.automatic);
  const ready = options.filter((option) => (option.missing ?? []).length === 0);

  //: 「没选」这一格说的是**实际会怎样**:只配好一家就自动用它;几家都配好就会在生成时问;
  //: 一家都没有就去插件页装。一条横线什么都没说。
  const unsetLabel =
    options.length === 0
      ? t("assetLinkNone")
      : automatic
        ? t("assetLinkAuto").replace("{name}", automatic.name)
        : ready.length > 1
          ? t("assetLinkAsk")
          : t("assetLinkNoneReady");

  const unready = options.filter((option) => (option.missing ?? []).length > 0);

  return (
    <SettingsGroup title={t("assetLinkTitle")} description={t("assetLinkDesc")}>
      <SettingsRow
        label={t("assetLinkStorage")}
        //: 没配好的不进下拉(选了也用不了),但要在这里说清缺什么 —— 否则用户不知道它为什么不在。
        description={
          unready.length
            ? unready.map((option) => t("assetLinkMissing").replace("{name}", option.name).replace("{fields}", (option.missing ?? []).join("、"))).join(" ")
            : undefined
        }
        controlClassName="w-full min-w-0 shrink"
        className="grid-cols-[140px_minmax(0,1fr)]"
      >
        <OptionPicker
          key={state.data?.current ?? UNSET}
          value={state.data?.current ?? UNSET}
          disabled={ready.length === 0 || save.isPending}
          onChange={(value) => save.mutate(value === UNSET ? null : value)}
          options={[
            { value: UNSET, label: unsetLabel },
            ...ready.map((option) => ({ value: option.instance_id, label: option.name })),
          ]}
          className="w-full min-w-0"
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
