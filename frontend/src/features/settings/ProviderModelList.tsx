import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, SlidersHorizontal, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/app/combobox";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { ModelSettingsDialog } from "@/features/settings/ModelSettingsDialog";
import { SettingsList, SettingsListItem } from "@/features/settings/ui";

type ProviderModel = components["schemas"]["ProviderModelOut"];

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
}: {
  profileId: string;
  vendor?: string;
  vendorLabel?: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<string | null>(null);

  const models = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`),
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
    // 能力默认的候选就是这些模型 —— 加/删/停用一个,那边的下拉必须跟着变。
    void qc.invalidateQueries({ queryKey: ["provider-defaults"] });
    void qc.invalidateQueries({ queryKey: ["capability-models"] });
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

  // ComfyUI 的选择单位是**工作流**不是模型 —— 它是个工作流引擎,没有模型目录可言。
  // 但交互完全一样(加入 / 启停 / 设能力 / 删除),所以走同一套行,只换文案:后端把
  // 实例里保存的工作流当成这条连接的"目录"返回(见 settings._catalog_entries)。
  // 在前端分叉成两个组件的话,两边的行样式和批量选择迟早各长各的。
  const isWorkflowUnit = vendor === "comfyui";
  const unit = {
    add: isWorkflowUnit ? t("workflowAddPlaceholder") : t("modelAddPlaceholder"),
    search: isWorkflowUnit ? t("workflowSearchPlaceholder") : t("modelSearchPlaceholder"),
    empty: isWorkflowUnit ? t("workflowNoMatch") : t("modelNoMatch"),
    custom: isWorkflowUnit ? t("workflowAddCustom") : t("modelAddCustom"),
    gone: isWorkflowUnit ? t("workflowNotInInstance") : t("modelNotInCatalog"),
  };

  const rows = models.data ?? [];
  const configured = rows.filter((row) => row.configured);
  const available = rows.filter((row) => !row.configured);

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

  return (
    <div className="grid gap-1.5">
      {models.isPending && (
        <span className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          <Loader2 size={12} className="animate-spin" />
          {t("modelListLoading")}
        </span>
      )}

      {/* 这个列表内嵌在展开的供应商行里,没有自己的标题栏 —— 入口就贴在列表右上角。
          只有一个模型时不给:对一行做"批量"没有意义。 */}
      {configured.length > 1 && !bulk.active && (
        <div className="flex justify-end">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} />
        </div>
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
              {(row.effective_capability_ids ?? []).map((capability) => (
                <span className="rounded bg-secondary px-1 py-px text-ui-2xs text-muted-foreground" key={capability}>
                  {capability}
                </span>
              ))}
              {row.context_window ? (
                <span className="timecode text-ui-2xs text-muted-foreground">
                  {Math.round(row.context_window / 1000)}k
                  {row.context_window_source === "override" ? ` · ${t("modelWindowManual")}` : ""}
                </span>
              ) : null}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Switch
              checked={row.enabled}
              aria-label={t("modelEnabled")}
              onCheckedChange={(next) => patch.mutate({ modelId: row.id, body: { enabled: next } })}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={t("modelSettingsTitle")}
              onClick={() => setEditing(row.id)}
            >
              <SlidersHorizontal size={13} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
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

      {/* 一个带搜索的入口,取代原来的「展开目录清单」+「手填 id」两处。
       *
       * 目录动辄两三百个模型(百炼 233 个),铺成一列既滚不完也找不到 —— 而用户来这里时
       * 通常已经知道要哪个,缺的是"输入几个字母就定位"。手填也并进来:目录里没有就直接用
       * 输入的那个,不必先意识到"这个模型不在目录里"再去找另一个框。 */}
      <Combobox
        value=""
        options={available.map((row) => ({ value: row.id }))}
        placeholder={unit.add}
        searchPlaceholder={unit.search}
        emptyText={unit.empty}
        allowCustomValue
        customValueLabel={(query) => unit.custom.replace("{id}", query)}
        className="h-8 w-full text-ui-sm"
        onValueChange={(modelId) => {
          const trimmed = modelId.trim();
          if (trimmed) add.mutate(trimmed);
        }}
      />
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
