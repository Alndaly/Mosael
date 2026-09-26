import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SlidersHorizontal, Tags, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/app/combobox";
import { BulkActionBar, BulkCheckbox, useBulkSelection } from "@/components/app/bulkSelection";
import { ModalShell } from "@/components/app/modals";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ModelSettingsDialog } from "@/features/settings/ModelSettingsDialog";
import { SettingsList, SettingsListItem } from "@/components/settings/settings-layout";
import { CAPABILITY_TAGS, orderedCapabilities } from "@/features/settings/capabilityTags";
import { GENERATION_KINDS } from "@/lib/generationCapabilities";

type ProviderModel = components["schemas"]["ProviderModelOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];

/** 模型行上的能力标签:短名 + 与设置侧栏同一套的图标。自动识别的(行上没标过)画成虚线框。 */
function CapabilityChips({ ids, auto }: { ids: string[]; auto: boolean }) {
  const t = useI18n();
  const chip = cn(
    "inline-flex items-center gap-0.5 rounded border px-1 py-px text-ui-2xs text-muted-foreground",
    auto ? "border-dashed border-border" : "border-transparent bg-secondary",
  );
  if (ids.length === 0) return <span className={cn(chip, "border-dashed border-border bg-transparent")}>{t("modelCapabilitiesNone")}</span>;
  return (
    <>
      {orderedCapabilities(ids).map((id) => {
        const tag = CAPABILITY_TAGS[id];
        const Icon = tag?.icon;
        return (
          <span className={chip} key={id}>
            {Icon && <Icon size={10} aria-hidden />}
            {tag ? t(tag.label) : id}
          </span>
        );
      })}
    </>
  );
}

/**
 * 一条连接下的模型列表。
 *
 * **这是"点击配置只会弹出一个模型的配置"那个问题真正被解决的地方**。此前卡片只显示
 * default_model 一个模型 —— 因为档案的粒度本身是混的:有的是一条连接(一个端点多个模型),
 * 有的其实是一个模型(用户拿模型名当了档案名)。现在连接展开就是它下面的所有模型。
 *
 * 列表是**已配置的行 + 目录里还没配的**合并而来:目录说端点有什么(会变),模型行说用户做过
 * 什么(不该被目录冲掉)。已配置的排在前面 —— 那是实际在用的;目录里的其余项跟在后面,
 * 一键加入。目录查不到的模型(私有部署、别名)可以手填,和目录来的平权。
 */
export function ProviderModelList({
  profileId,
  vendor,
  vendorLabel,
  action,
  onActionDone,
}: {
  profileId: string;
  vendor?: string;
  vendorLabel?: string;
  /** 连接行溢出菜单发下来的动作(添加模型 / 进入选择)。数据与弹窗都在这层,
      菜单只发信号 —— 执行完要回报,否则同一个动作点第二次不会再来一遍。 */
  action?: { kind: "add" | "bulk"; at: number } | null;
  onActionDone?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<string | null>(null);

  const models = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`),
  });
  const vendorPresets = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<VendorPreset[]>("/api/settings/provider-vendors"),
    staleTime: 300_000,
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
    // 能力默认的候选就是这些模型 —— 加/删/停用一个,那边的下拉必须跟着变。
    void qc.invalidateQueries({ queryKey: ["provider-defaults"] });
    void qc.invalidateQueries({ queryKey: ["capability-models"] });
    // 生成选择器也是这些模型(能力标签决定它进不进生图 / 视频下拉)。
    void qc.invalidateQueries({ queryKey: ["generation-options"] });
  };

  const add = useMutation({
    mutationFn: (modelId: string) =>
      api(`/api/settings/providers/${profileId}/models`, {
        method: "POST",
        body: JSON.stringify({ model_id: modelId, enabled: true }),
      }),
    onSuccess: invalidate,
  });
  const patch = useMutation({
    mutationFn: ({ modelId, body }: { modelId: string; body: Record<string, unknown> }) =>
      api(`/api/settings/providers/${profileId}/models/${encodeURIComponent(modelId)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (modelId: string) =>
      api(`/api/settings/providers/${profileId}/models/${encodeURIComponent(modelId)}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const unit = {
    add: t("modelAddPlaceholder"),
    search: t("modelSearchPlaceholder"),
    empty: t("modelNoMatch"),
    custom: t("modelAddCustom"),
    gone: t("modelNotInCatalog"),
  };

  const rows = models.data ?? [];
  const configured = rows.filter((row) => row.configured);
  const available = rows.filter((row) => !row.configured);

  /* 这条连接能做生成,而它下面的模型一个都没被认成生成模型 —— 那多半是聚合端点上一排认不出名字的模型
     (147ai、Ollama),它们现在只当对话模型。说一句该去哪里标,不然用户只会看到生图下拉里是空的。 */
  const presetCapabilities = vendorPresets.data?.find((preset) => preset.vendor === vendor)?.capability_ids ?? [];
  const connectionGenerates = presetCapabilities.some((id) => (GENERATION_KINDS as readonly string[]).includes(id));
  const noGenerationModel =
    configured.length > 0 &&
    !configured.some((row) =>
      (row.effective_capability_ids ?? []).some((id) => (GENERATION_KINDS as readonly string[]).includes(id)),
    );
  const untaggedHint =
    connectionGenerates && noGenerationModel
      ? presetCapabilities.includes("chat")
        ? t("modelCapabilitiesChatOnlyHint")
        : t("modelCapabilitiesUnknownHint")
      : null;

  /* 一个端点常常一次加进来十几个模型,之后"只留对话的、其余停用"是常见动作。
     逐个点开关的话,这件事要点十几次,中间还会点错行。 */
  const bulk = useBulkSelection(configured, (row) => row.id);
  const patchMany = useMutation({
    mutationFn: async ({ ids, body }: { ids: string[]; body: Record<string, unknown> }) => {
      await Promise.allSettled(
        ids.map((id) =>
          api(`/api/settings/providers/${profileId}/models/${encodeURIComponent(id)}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          }),
        ),
      );
    },
    onSuccess: () => {
      bulk.clear();
      invalidate();
    },
  });
  const removeMany = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.allSettled(
        ids.map((id) => api(`/api/settings/providers/${profileId}/models/${encodeURIComponent(id)}`, { method: "DELETE" })),
      );
    },
    onSuccess: () => {
      bulk.clear();
      invalidate();
    },
  });
  const busy = patchMany.isPending || removeMany.isPending;

  /* 「选择」没有自己的常驻入口:它和其他两个动作一起住在连接行的溢出菜单里,菜单发信号、
     这里执行。只有一个模型时不进入 —— 对一行做"批量"没有意义。 */
  React.useEffect(() => {
    if (action?.kind !== "bulk") return;
    if (configured.length > 1) bulk.enter();
    onActionDone?.();
  }, [action, configured.length, bulk, onActionDone]);

  const actionOpen = (kind: "add") => action?.kind === kind;

  /* 添加模型弹窗的候选。每次动作重新打开都从空开始 —— 上回挑了一半的值不该留着。 */
  const [picked, setPicked] = React.useState("");
  React.useEffect(() => {
    if (action?.kind === "add") setPicked("");
  }, [action]);

  return (
    <div className="grid gap-1.5">
      {/* **占位要长在真实行的容器里。** 此前这里是一条左对齐的裸文字,既没有行高也没有内边距,
          于是它贴在展开区的边上,和下面将要出现的模型行对不齐 —— 加载完还会整片跳一下。
          用同一套 SettingsList / SettingsListItem 铺三行骨架:版面先占住,内容到了就地替换。
          行数固定三行是有意的:它表示"正在来",不表示"有三个" —— 真实数量此刻还不知道。 */}
      {models.isPending && (
        <SettingsList aria-busy="true" aria-label={t("modelListLoading")}>
          {[0, 1, 2].map((index) => (
            <SettingsListItem className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2" key={index}>
              <div className="grid gap-1.5">
                {/* 名字那一行长短不一 —— 三块等宽反而更像一张表格,不像一份清单。 */}
                <Skeleton className="h-3.5" style={{ width: `${[42, 58, 34][index]}%` }} />
                <Skeleton className="h-2.5 w-[28%]" />
              </div>
              {/* 右侧是开关 + 两个图标按钮,占位也照这个宽度留着,免得加载完右栏横向跳。 */}
              <Skeleton className="h-5 w-[64px] rounded-full" />
            </SettingsListItem>
          ))}
        </SettingsList>
      )}

      <BulkActionBar active={bulk.active} count={bulk.count} allSelected={bulk.allSelected} onToggleAll={bulk.toggleAll} onExit={bulk.exit}>
        <Button variant="outline" size="sm" disabled={busy} loading={patchMany.isPending} onClick={() => patchMany.mutate({ ids: bulk.selectedIds, body: { enabled: true } })}>
          {t("bulkEnable")}
        </Button>
        <Button variant="outline" size="sm" disabled={busy} loading={patchMany.isPending} onClick={() => patchMany.mutate({ ids: bulk.selectedIds, body: { enabled: false } })}>
          {t("bulkDisable")}
        </Button>
        <Button variant="outline" size="sm" disabled={busy} loading={removeMany.isPending} onClick={() => removeMany.mutate(bulk.selectedIds)}>
          <Trash2 size={12} /> {t("bulkDelete")}
        </Button>
      </BulkActionBar>

      {untaggedHint && (
        <p className="m-0 flex items-start gap-1.5 px-1 text-xs leading-[1.45] text-muted-foreground">
          <Tags size={12} className="mt-[3px] shrink-0" aria-hidden />
          {untaggedHint}
        </p>
      )}

      <SettingsList>
        {configured.map((row) => (
          <SettingsListItem
            className={cn(
              "grid items-center gap-2",
              bulk.active ? "grid-cols-[auto_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]",
              bulk.isSelected(row.id) && "rounded-md bg-[color-mix(in_srgb,var(--primary)_7%,transparent)]",
            )}
            key={row.id}
          >
          {bulk.active && (
            <BulkCheckbox
              checked={bulk.isSelected(row.id)}
              onToggle={(event) => bulk.toggle(row.id, event)}
              label={t("bulkSelectRow")}
            />
          )}
          <div className="grid min-w-0 gap-0.5">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-ui-sm font-medium text-foreground">{row.display_name || row.id}</span>
              {/* 目录里已经没有它了:不删,别名与私有部署仍要能用,但得说出来 —— 否则用户
                  只会看到"模型突然不工作了"却不知道端点那边已经下线了它。 */}
              {!row.in_catalog && <Badge variant="outline">{unit.gone}</Badge>}
            </span>
            <span className="flex flex-wrap items-center gap-1">
              {/* 能力标签**就是改能力的入口**:认不出的模型现在只当对话模型(或什么都不是),要让它出图,
                  用户得一眼看到"它现在被当成什么",并且点一下就能改。自动识别的用虚线框,和"我标过的"分开。 */}
              <button
                type="button"
                className="flex cursor-pointer flex-wrap items-center gap-1 rounded border-0 bg-transparent p-0 hover:opacity-80"
                aria-label={t("modelCapabilitiesEdit")}
                title={(row.capability_ids ?? []).length === 0 ? t("modelCapabilitiesAuto") : t("modelCapabilitiesEdit")}
                onClick={() => setEditing(row.id)}
              >
                <CapabilityChips ids={row.effective_capability_ids ?? []} auto={(row.capability_ids ?? []).length === 0} />
              </button>
              {row.context_window ? (
                <span className="timecode text-ui-2xs text-muted-foreground">
                  {Math.round(row.context_window / 1000)}k
                  {row.context_window_source === "override" ? ` · ${t("modelWindowManual")}` : ""}
                </span>
              ) : null}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {/* 开关右边要多留一截。视觉上的间距是 gap 加上两侧控件自己的内边距:两个幽灵图标
                按钮之间有 4 + 7.5 + 7.5 ≈ 19px,而开关是一块实心胶囊、内边距为 0,同样的
                gap 只剩 11.5px —— 它就贴在了参数按钮上。 */}
            <Switch
              className="mr-2"
              checked={row.enabled}
              aria-label={t("modelEnabled")}
              onCheckedChange={(next) => patch.mutate({ modelId: row.id, body: { enabled: next } })}
            />
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={t("modelSettingsTitle")}
              onClick={() => setEditing(row.id)}
            >
              <SlidersHorizontal size={13} />
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={t("delete")}
              loading={remove.isPending && remove.variables === row.id}
              onClick={() => remove.mutate(row.id)}
            >
              <Trash2 size={13} />
            </Button>
          </div>
          </SettingsListItem>
        ))}
      </SettingsList>

      {/* 添加模型与自定义参数组的弹窗:入口统一在连接行的溢出菜单里(见 ProviderProfilesSection),
          列表本体只剩模型行 —— 列表级动作不再各自占一行浮在首尾。 */}
      <ModalShell
        open={actionOpen("add")}
        onOpenChange={(next) => !next && onActionDone?.()}
        title={t("modelAddEntry")}
        footer={
          <>
            <Button variant="outline" onClick={() => onActionDone?.()}>{t("cancel")}</Button>
            {/* 选中即提交的交互撤掉了:挑错一个目录项就多发一次请求,而撤销要再去删一行。
                先挑后确认 —— 确认才 POST,取消什么都不发生。 */}
            <Button
              disabled={!picked.trim()}
              loading={add.isPending}
              onClick={() => add.mutate(picked.trim(), { onSuccess: () => onActionDone?.() })}
            >
              {t("modelAdd")}
            </Button>
          </>
        }
      >
        {/* 一个带搜索的入口,取代原来的「展开目录清单」+「手填 id」两处。
         *
         * 目录动辄两三百个模型(百炼 233 个),铺成一列既滚不完也找不到 —— 而用户来这里时
         * 通常已经知道要哪个,缺的是"输入几个字母就定位"。手填也并进来:目录里没有就直接用
         * 输入的那个,不必先意识到"这个模型不在目录里"再去找另一个框。 */}
        <Combobox
          value={picked}
          options={available.map((row) => ({ value: row.id }))}
          placeholder={unit.add}
          searchPlaceholder={unit.search}
          emptyText={unit.empty}
          allowCustomValue
          customValueLabel={(query) => unit.custom.replace("{id}", query)}
          onValueChange={setPicked}
        />
      </ModalShell>
      {vendorLabel && <span className="sr-only">{vendorLabel}</span>}

      {editing && (
        <ModelSettingsDialog
          profileId={profileId}
          modelId={editing}
          vendor={vendor}
          open
          onOpenChange={(next) => {
            if (!next) {
              setEditing(null);
              invalidate();
            }
          }}
        />
      )}
    </div>
  );
}
