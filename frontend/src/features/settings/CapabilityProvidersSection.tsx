/**
 * 「能力提供方」(ADR 0031 §5、ADR 0032):宿主的几项能力各用哪一家 —— 素材外链(本地素材传到哪一家对象存储换直链)、
 * 文档解析(本地解析还是 MinerU……)、降噪、分离人声(本机引擎还是插件)。一项能力一组,照后端的能力表列
 * (GET /api/settings/capabilities),每组下面收着「用在哪」。
 *
 * **一项能力一张卡片。** 此前组与组之间只有一条发丝线,七组摞在一起像一份长列表 —— 维护者原话:「能力提供方
 * 这个页面 UI 非常差劲,排版很乱让人无从下手」。七项能力是七件互不相干的事,卡片自带的分区比一条线清楚。
 * 卡片外壳用 `SettingsGroup card`(共享的 `SETTINGS_CARD`),不在这里另造一套框。
 *
 * **"现在用谁"写在标题行**(「降噪 · 内置降噪」)。此前要先在组说明下面找到那个灰标签、再看右边的下拉才知道
 * 现在用的是哪一家;标题行一眼就答。
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
import { CapabilityUseSummary } from "@/components/settings/CapabilityUseList";
import {
  SETTINGS_CARD,
  SETTINGS_FIELD_WIDTH,
  SettingsEmpty,
  SettingsGroup,
  SettingsItemNote,
  SettingsItemRow,
  SettingsTag,
} from "@/components/settings/settings-layout";
import { PageLoadError } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { findPluginsFor } from "@/lib/deepLink";

const UNSET = "__unset__";
const KEY = capabilityKeys.choices();

/**
 * 一页并列着七项能力:卡片与卡片之间留一个分区间距(不是发丝线)。
 * 装在一个容器里,而不是直接作为 `SettingsSectionStack` 的孩子 —— 那一层会给相邻的
 * `[data-slot=settings-group]` 画线,卡片自己已经有边框了。
 */
const CARD_STACK = "mt-6 grid gap-4";

/** 一家都没有时怎么说:素材外链要去建一个对象存储连接;别的能力说句通用的。 */
const NONE_HINT: Record<string, MessageKey> = { public_url: "assetLinkNone" };
//: 有几家、可一家都没配好时同理:「填上桶和密钥」只对素材外链成立。此前转写也这么说,把想转写的人指去了对象存储
//: (体检 UM-06);别的能力说句中性的,缺什么由下面一家一行写清。
const NONE_READY_HINT: Record<string, MessageKey> = { public_url: "assetLinkNoneReady" };

/** 控件行左边那个标签:14px 深色,和组说明的灰分得开 —— 它标的是一个要操作的行,不是又一句解释。 */
function ControlLabel({ children }: { children: React.ReactNode }) {
  return (
    <span data-capability-control-label="" className="text-ui-sm font-medium text-foreground">
      {children}
    </span>
  );
}

/** 标题行里的「现在用谁」。样式由 `SettingsGroup` 的 `titleAdornment` 那一格给(安静的灰字)。 */
function CurrentSelection({ children }: { children: React.ReactNode }) {
  return <span data-capability-current="">{children}</span>;
}

export function CapabilityProvidersSection() {
  const state = useQuery({ queryKey: KEY, queryFn: listCapabilityChoices });
  //: 后端要把每一家「装好了没有」问一遍(本机引擎要起子进程探),刚启动时要几秒。此前那几秒整页一片白、
  //: 看不出是在加载还是坏了(用户:「很长时间的白屏,也没有 Skeleton 或者 loading」)。
  if (state.isPending) return <CapabilityGroupsSkeleton />;
  if (state.isError) {
    return <PageLoadError size="section" icon={<Plug size={20} />} error={state.error} onRetry={() => void state.refetch()} />;
  }
  //: 空表 = 后端一项走挑法的能力都没登记(domain/capabilities.registered())。这和**某一项能力还没有
  //: 一家连接**是两回事 —— 后者在那个组里已经有一句 capabilityNone。此前这里只剩页头、底下一片空白,
  //: 看着像这一页坏了;说清是这一版还没登记,并给出下一步。
  const groups = state.data ?? [];
  if (groups.length === 0) return <CapabilityProvidersEmpty />;
  return (
    <div data-capability-cards="" className={CARD_STACK}>
      {groups.map((choices) =>
        choices.defaultable === false
          ? <ProvidersOnlyGroup key={choices.capability} choices={choices} />
          : <CapabilityGroup key={choices.capability} choices={choices} />,
      )}
    </div>
  );
}

/** 后端还没登记任何能力:这一页没有可配的,直接说明白,不是一个空白页。 */
function CapabilityProvidersEmpty() {
  const t = useI18n();
  return (
    <SettingsEmpty
      icon={<Store size={20} />}
      title={t("capabilityEmpty")}
      body={t("capabilityEmptyNote")}
    />
  );
}

/** 骨架里一组的长相:标题行(名字 + 现在用谁)、说明几行、有没有下拉、「用在哪」收着几处。不写名字和文案 —— 那些只有后端一份。 */
type CapabilitySkeletonShape = {
  /** 组标题那一小条 —— 真页的标题是两三个字,一条窄的。 */
  title: string;
  /** 标题行里「现在用谁」那一条的宽度。 */
  current: string;
  /** 组说明占几行、每行多宽。真页有的只有一行,有的两行。 */
  description: readonly string[];
  /** 这一组有没有「用哪一家」的下拉。没有的那两组(分离人声、配音)真页只写一行字 / 只列候选。 */
  picker: boolean;
  /** 「用在哪」收着几处。0 = 这一组没有用法(真页那几组不画摘要行)。 */
  uses: number;
};

/**
 * 骨架**照真实页的分组**铺:后端能力表今天登记的 7 项(`domain/capabilities.registered()`,按名字排)——
 * 降噪、分离人声、文档解析、素材外链、配音、转写、翻译。这里只记每组的形状(标题多长、说明几行、
 * 有没有下拉、用在哪几处),不写能力的名字和文案:那些只有后端那一份(见 `api/domains/capabilities`)。
 *
 * **组数必须和能力表一致**:骨架多一组少一组,数据到了页面就会跳一下。后端新登记一项能力时来这里补一行 ——
 * `CapabilityProvidersSection.dom.test.tsx` 拿它和真实数据的 7 组对齐。
 */
export const CAPABILITY_SKELETON_GROUPS: readonly CapabilitySkeletonShape[] = [
  //: 降噪:说明两行,有下拉,底下还收着一行「用在 3 处」。
  { title: "w-16", current: "w-14", description: ["w-3/5", "w-2/5"], picker: true, uses: 3 },
  //: 分离人声:只有一行字,没有下拉(「目前只有这一家」),没有用法。
  { title: "w-20", current: "w-24", description: ["w-2/5"], picker: false, uses: 0 },
  //: 文档解析:一行,有下拉,没有用法。
  { title: "w-20", current: "w-16", description: ["w-1/2"], picker: true, uses: 0 },
  //: 素材外链:一行,有下拉(一家都没有时那个位置是「去插件页」按钮,同样是右边一格)。
  { title: "w-16", current: "w-16", description: ["w-2/5"], picker: true, uses: 0 },
  //: 配音:没有默认,只列候选,底下收着一行「用在 1 处」—— 没有下拉。
  { title: "w-12", current: "w-20", description: ["w-3/5"], picker: false, uses: 1 },
  //: 转写:说明两行,有下拉,没有用法。
  { title: "w-16", current: "w-16", description: ["w-4/5", "w-1/3"], picker: true, uses: 0 },
  //: 翻译:一行,有下拉,没有用法。
  { title: "w-16", current: "w-16", description: ["w-1/2"], picker: true, uses: 0 },
];

/**
 * 加载中的一组:壳用真页 `SettingsGroup card` 的同一套(同一个 `data-slot="settings-group"`、卡片外壳、
 * 抬头/标题/正文那一圈类名),组里那一行也用真的 `SettingsItemRow` —— 卡与卡的间距由 `CARD_STACK` 给,
 * 不另写一套间距。灰条只是把真页的字换成了 <Skeleton>。
 *
 * 读屏那边:第一组里放一句 `role="status"` + `aria-busy` + `aria-live` 的 sr-only 说明,灰条整块 `aria-hidden` ——
 * 一屏占位不该被念成「这里有七组能力」。
 */
function CapabilitySkeletonGroup({ shape, label }: { shape: CapabilitySkeletonShape; label?: string }) {
  return (
    <section
      data-slot="settings-group"
      data-settings-card=""
      data-capability-skeleton-group=""
      aria-hidden={label ? undefined : "true"}
      className={cn("@container/settings grid gap-1", SETTINGS_CARD)}
    >
      {label && (
        <span role="status" aria-live="polite" aria-busy="true" data-capability-loading="" className="sr-only">
          {label}
        </span>
      )}
      <div data-capability-skeleton-content="" aria-hidden="true" className="contents">
        <header
          data-slot="settings-group-header"
          className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-4 pt-4 pb-2"
        >
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <h2 data-slot="settings-group-title" className={cn("m-0 font-semibold leading-snug tracking-tight", "text-ui-md")}>
                <Skeleton data-capability-skeleton-title="" className={cn("h-5", shape.title)} />
              </h2>
              {/*: 标题行里「现在用谁」那一格 —— 真页的当前选择就在名字旁边。 */}
              <span data-slot="settings-group-adornment" className="inline-flex min-w-0 items-center gap-1.5 text-ui-sm font-normal leading-snug text-muted-foreground">
                <span aria-hidden>·</span>
                <Skeleton data-capability-skeleton-current="" className={cn("h-3.5", shape.current)} />
              </span>
            </div>
            {/*: 说明那一格和真页的说明同一档字号/颜色/边距,只多一层 `grid gap-1.5` 把几条灰条竖着排。
                真页的说明不再限宽(整页宽的面板里 42rem 会留出右侧一大块空白),骨架也不留 —— 加载前后行宽一致。 */}
            <div
              data-slot="settings-group-description"
              className="mb-0 mt-1.5 grid gap-1.5 text-ui-sm leading-[1.55] text-muted-foreground"
            >
              {shape.description.map((width, index) => (
                <Skeleton key={index} data-capability-skeleton-description="" className={cn("h-3.5", width)} />
              ))}
            </div>
          </div>
          {/*: 组抬头右边是「去插件市场找」—— 真页每一张卡片的右上角都是它,骨架也占住这一格。 */}
          <div data-slot="settings-group-actions" className="flex shrink-0 items-center gap-2">
            <Skeleton className="h-8 w-24 rounded-full" />
          </div>
        </header>
        <div data-slot="settings-group-content" className="grid [&>*+*]:border-t [&>*+*]:border-divider px-4">
          <SettingsItemRow
            label={<Skeleton data-capability-skeleton-label="" className="h-3.5 w-20" />}
            description={shape.picker ? <Skeleton className="h-3 w-2/5" /> : undefined}
          >
            {shape.picker && (
              //: 和真页的下拉同一格:设置字段那一档高(CONTROL_HEIGHT.md)、同一个宽度。
              <Skeleton
                data-capability-skeleton-control=""
                className={cn(CONTROL_HEIGHT.md, "rounded-md", SETTINGS_FIELD_WIDTH)}
              />
            )}
          </SettingsItemRow>
          {shape.uses > 0 && (
            //: 真页那一行「用在 N 处」:左边一句摘要,右边类别 + 箭头。收起时没有标签。
            <div data-capability-skeleton-uses="" className="flex min-w-0 items-center justify-between gap-2 py-3">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3.5 w-16" />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

/** 加载中:照**真实页的分组**一组一组铺(不是一排一样长的条),组数见 `CAPABILITY_SKELETON_GROUPS`。 */
function CapabilityGroupsSkeleton() {
  const t = useI18n();
  return (
    <div data-capability-cards="" className={CARD_STACK}>
      {CAPABILITY_SKELETON_GROUPS.map((shape, index) => (
        <CapabilitySkeletonGroup key={index} shape={shape} label={index === 0 ? t("pageLoading") : undefined} />
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
    <SettingsGroup
      card
      title={choices.label}
      titleAdornment={<CurrentSelection>{t("capabilityNoDefaultShort")}</CurrentSelection>}
      description={toPlainText(choices.description)}
      actions={<FindPlugins capability={choices.capability} />}
    >
      <SettingsItemRow
        label={<ControlLabel>{t("capabilityProviders")}</ControlLabel>}
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
      />
      {uses.length > 0 && <CapabilityUseSummary uses={uses} />}
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
  //: 标题行里「现在用谁」:点名了就是点名那一家;没点名但有一个自动的内置实现,用的就是它;
  //: 两者都没有就照实说「未指定」,不写成一句要读半行的解释。
  const currentName = choices.current
    ? options.find((option) => option.id === choices.current)?.name ?? choices.current
    : automaticBuiltin?.name ?? t("capabilityUnset");

  return (
    <SettingsGroup
      card
      title={choices.label}
      titleAdornment={<CurrentSelection>{currentName}</CurrentSelection>}
      description={toPlainText(choices.description)}
      actions={<FindPlugins capability={choices.capability} />}
    >
      <SettingsItemRow
        label={<ControlLabel>{t("capabilityProvider")}</ControlLabel>}
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
      >
        {options.length === 0 ? (
          <Button asChild size="sm" variant="outline">
            <a href="#/plugins">{t("capabilityGoPlugins")}</a>
          </Button>
        ) : nothingElse ? null : (
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
      {uses.length > 0 && <CapabilityUseSummary uses={uses} />}
    </SettingsGroup>
  );
}

/** 「谁还能做这件事」:去插件市场,只看能做这一项的插件(ADR 0032 §5)。 */
function FindPlugins({ capability }: { capability: string }) {
  const t = useI18n();
  return (
    <Button size="sm" variant="ghost" onClick={() => findPluginsFor(capability)}>
      <Store aria-hidden />
      {t("capabilityFindPlugins")}
    </Button>
  );
}
