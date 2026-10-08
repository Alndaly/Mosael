/**
 * 「能力提供方」(ADR 0031 §5、ADR 0032):宿主的几项能力各用哪一家 —— 素材外链(本地素材传到哪一家对象存储换直链)、
 * 文档解析(本地解析还是 MinerU……)、降噪、分离人声(本机引擎还是插件)。一项能力一组,照后端的能力表列
 * (GET /api/settings/capabilities),每组下面列「用在哪」。
 *
 * **放在设置里,不放在插件页。** 它是一个跨插件的个人选择(几家里用哪一家),和默认模型同类;放在每一家连接上
 * 是几个互相牵制的开关 —— 打开一家会悄悄关掉另一家,想知道现在用的是哪家还得挨个点开看。挑法见
 * backend/app/domain/capabilities。
 */
import React from "react";
import { CircleDashed, Plug, Store } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { capabilityKeys } from "@/api/queryKeys";
import { listCapabilityChoices, setCapabilityDefault, type CapabilityChoices as Choices } from "@/api/domains/capabilities";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { OptionPicker } from "@/components/ui/option-picker";
import { CapabilityUseList } from "@/components/settings/CapabilityUseList";
import {
  SETTINGS_FIELD_WIDTH,
  SettingsGroup,
  SettingsItemNote,
  SettingsItemRow,
  SettingsItemState,
  SettingsTag,
} from "@/components/settings/settings-layout";
import { PageLoadError } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { findPluginsFor } from "@/lib/deepLink";

const UNSET = "__unset__";
const KEY = capabilityKeys.choices();

/** 一家都没有时怎么说:素材外链要去建一个对象存储连接;别的能力说句通用的。 */
const NONE_HINT: Record<string, MessageKey> = { public_url: "assetLinkNone" };
//: 有几家、可一家都没配好时同理:「填上桶和密钥」只对素材外链成立。此前转写也这么说,把想转写的人指去了对象存储
//: (体检 UM-06);别的能力说句中性的,缺什么由下面一家一行写清。
const NONE_READY_HINT: Record<string, MessageKey> = { public_url: "assetLinkNoneReady" };

export function CapabilityProvidersSection() {
  const state = useQuery({ queryKey: KEY, queryFn: listCapabilityChoices });
  //: 后端要把每一家「装好了没有」问一遍(本机引擎要起子进程探),刚启动时要几秒。此前那几秒整页一片白、
  //: 看不出是在加载还是坏了(用户:「很长时间的白屏,也没有 Skeleton 或者 loading」)。
  if (state.isPending) return <CapabilityGroupsSkeleton />;
  if (state.isError) {
    return <PageLoadError size="section" icon={<Plug size={20} />} error={state.error} onRetry={() => void state.refetch()} />;
  }
  return (
    <>
      {(state.data ?? []).map((choices) =>
        choices.defaultable === false
          ? <ProvidersOnlyGroup key={choices.capability} choices={choices} />
          : <CapabilityGroup key={choices.capability} choices={choices} />,
      )}
    </>
  );
}

/** 加载中:照一组能力的样子(标题、说明、一行选择)占位,几组排下来 —— 数据到了原地换上,页面不跳。 */
function CapabilityGroupsSkeleton() {
  return (
    <div data-capability-loading="" aria-busy="true" className="grid gap-10">
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="grid gap-3 px-0.5">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-3.5" style={{ width: `${[58, 46, 64, 52][index]}%` }} />
          <div className="flex items-center justify-between gap-6 border-t border-divider pt-5">
            <div className="grid flex-1 gap-2">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3 w-2/5" />
            </div>
            <Skeleton className={cn("h-9 rounded-md", SETTINGS_FIELD_WIDTH)} />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * 没有「默认用哪家」的能力(配音:引擎和音色成对选,每个入口都点名)。不摆选择器 —— 摆了也改变不了任何地方 ——
 * 只列有哪几家、没配好的缺什么、用在哪。
 */
function ProvidersOnlyGroup({ choices }: { choices: Choices }) {
  const t = useI18n();
  const options = choices.options ?? [];
  const ready = options.filter((option) => (option.missing ?? []).length === 0);
  const unready = options.filter((option) => (option.missing ?? []).length > 0);
  const uses = choices.used_by ?? [];
  return (
    <SettingsGroup title={choices.label} description={toPlainText(choices.description)} actions={<FindPlugins capability={choices.capability} />}>
      <SettingsItemRow
        label={t("capabilityProviders")}
        description={t("capabilityNoDefault")}
        notes={
          <>
            {ready.length > 0 && (
              <div data-capability-ready="" className="flex flex-wrap gap-1.5 pt-1">
                {ready.map((option) => <SettingsTag key={option.id}>{option.name}</SettingsTag>)}
              </div>
            )}
            {unready.map((option) => (
              <SettingsItemNote key={option.id} icon={<CircleDashed size={13} aria-hidden />}>
                {t(option.builtin ? "capabilityBuiltinUnready" : "assetLinkMissing")
                  .replace("{name}", option.name)
                  .replace("{fields}", (option.missing ?? []).join(t("listSeparator")))}
              </SettingsItemNote>
            ))}
          </>
        }
        footer={uses.length > 0 ? <CapabilityUseList uses={uses} label={t("capabilityUsedBy")} /> : undefined}
      />
    </SettingsGroup>
  );
}

function CapabilityGroup({ choices }: { choices: Choices }) {
  const t = useI18n();
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (providerId: string | null) => setCapabilityDefault(choices.capability, providerId),
    onSuccess: (next) => qc.setQueryData<Choices[]>(KEY, (list) => (list ?? []).map((one) => (one.capability === next.capability ? next : one))),
  });

  const options = choices.options ?? [];
  //: 「不指定」这一项说的是**不指定时会怎样**。有允许自动的内置实现(本地解析、ffmpeg 降噪)就是它 —— 选它 = 清掉默认,
  //: 所以它不再单列;别的内置实现(DeepFilterNet、RNNoise……)和插件连接一样是可点名的一项(ADR 0032 §1)。
  const automatic = options.find((option) => option.id === choices.automatic);
  const automaticBuiltin = automatic?.builtin ? automatic : undefined;
  const ready = options.filter((option) => (option.missing ?? []).length === 0 && option.id !== automaticBuiltin?.id);
  const unready = options.filter((option) => (option.missing ?? []).length > 0);

  const unsetLabel = automaticBuiltin
    ? automaticBuiltin.name
    : options.length === 0
      ? t(NONE_HINT[choices.capability] ?? "capabilityNone")
      : ready.length === 0
        ? t(NONE_READY_HINT[choices.capability] ?? "capabilityNoneReady")
        : automatic
          ? t("assetLinkAuto").replace("{name}", automatic.name)
          : t("assetLinkAsk");
  const uses = choices.used_by ?? [];
  //: 除了「不指定」没有别的可选:不摆一个灰掉的下拉(像坏了),直接写出现在用的是哪一家、为什么只有它。
  const nothingElse = ready.length === 0 && !choices.current;

  return (
    <SettingsGroup title={choices.label} description={toPlainText(choices.description)} actions={<FindPlugins capability={choices.capability} />}>
      <SettingsItemRow
        label={t("capabilityProvider")}
        description={
          options.length === 0
            ? t(NONE_HINT[choices.capability] ?? "capabilityNone")
            : nothingElse
              ? automaticBuiltin ? t("capabilityOnlyOne") : unsetLabel
              : undefined
        }
        //: 没配好的不进下拉(选了也用不了),一家一行说清缺什么 —— 否则用户不知道它为什么不在。
        notes={unready.map((option) => (
          <SettingsItemNote key={option.id} icon={<CircleDashed size={13} aria-hidden />}>
            {t(option.builtin ? "capabilityBuiltinUnready" : "assetLinkMissing")
              .replace("{name}", option.name)
              .replace("{fields}", (option.missing ?? []).join(t("listSeparator")))}
          </SettingsItemNote>
        ))}
        //: 定了这一家,哪些地方跟着换 —— 后端从能力表现算(ADR 0032 §4),新的节点、工具声明了就出现在这里。
        footer={uses.length > 0 ? <CapabilityUseList uses={uses} label={t("capabilityUsedBy")} /> : undefined}
      >
        {options.length === 0 ? (
          <Button asChild size="sm" variant="outline">
            <a href="#/plugins">{t("capabilityGoPlugins")}</a>
          </Button>
        ) : nothingElse ? (
          automaticBuiltin && <SettingsItemState tone="muted">{automaticBuiltin.name}</SettingsItemState>
        ) : (
          <OptionPicker
            key={choices.current ?? UNSET}
            value={choices.current ?? UNSET}
            disabled={save.isPending}
            onChange={(value) => save.mutate(value === UNSET ? null : value)}
            options={[
              { value: UNSET, label: unsetLabel },
              ...ready.map((option) => ({ value: option.id, label: option.name })),
            ]}
            className={SETTINGS_FIELD_WIDTH}
          />
        )}
      </SettingsItemRow>
    </SettingsGroup>
  );
}

/** 「谁还能做这件事」:去插件市场,只看能做这一项的插件(ADR 0032 §5)。 */
function FindPlugins({ capability }: { capability: string }) {
  const t = useI18n();
  return (
    <Button size="xs" variant="ghost" onClick={() => findPluginsFor(capability)}>
      <Store size={12} aria-hidden />
      {t("capabilityFindPlugins")}
    </Button>
  );
}
