import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, SlidersHorizontal, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ModelSettingsDialog } from "@/features/settings/ModelSettingsDialog";
import { cn } from "@/lib/utils";

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
export function ProviderModelList({ profileId, vendorLabel }: { profileId: string; vendorLabel?: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [manualId, setManualId] = React.useState("");
  const [editing, setEditing] = React.useState<string | null>(null);

  const models = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`),
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
    // 能力默认的候选就是这些模型 —— 加/删/停用一个,那边的下拉必须跟着变。
    void qc.invalidateQueries({ queryKey: ["provider-defaults"] });
  };

  const add = useMutation({
    mutationFn: (modelId: string) =>
      api(`/api/settings/providers/${profileId}/models`, {
        method: "POST",
        body: JSON.stringify({ model_id: modelId, enabled: true }),
      }),
    onSuccess: () => {
      setManualId("");
      invalidate();
    },
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

  const rows = models.data ?? [];
  const configured = rows.filter((row) => row.configured);
  const available = rows.filter((row) => !row.configured);

  return (
    <div className="grid gap-1.5">
      {models.isPending && (
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Loader2 size={12} className="animate-spin" />
          {t("modelListLoading")}
        </span>
      )}

      {configured.map((row) => (
        <div
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-border bg-panel px-2.5 py-1.5"
          key={row.id}
        >
          <div className="grid min-w-0 gap-0.5">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-[12.5px] font-medium text-foreground">{row.display_name || row.id}</span>
              {/* 目录里已经没有它了:不删,别名与私有部署仍要能用,但得说出来 —— 否则用户
                  只会看到"模型突然不工作了"却不知道端点那边已经下线了它。 */}
              {!row.in_catalog && <Badge variant="outline">{t("modelNotInCatalog")}</Badge>}
            </span>
            <span className="flex flex-wrap items-center gap-1">
              {(row.effective_capability_ids ?? []).map((capability) => (
                <span className="rounded bg-secondary px-1 py-px text-[10px] text-muted-foreground" key={capability}>
                  {capability}
                </span>
              ))}
              {row.context_window ? (
                <span className="timecode text-[10px] text-muted-foreground">
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
              onClick={() => remove.mutate(row.id)}
            >
              <Trash2 size={13} />
            </Button>
          </div>
        </div>
      ))}

      {available.length > 0 && (
        <details className="rounded-md border border-dashed border-border px-2.5 py-1.5">
          <summary className="cursor-pointer text-[11.5px] text-muted-foreground">
            {t("modelFromCatalog").replace("{n}", String(available.length))}
          </summary>
          <div className="mt-1.5 grid gap-1">
            {available.map((row) => (
              <div className="flex items-center justify-between gap-2" key={row.id}>
                <span className="min-w-0 truncate text-[11.5px] text-foreground">{row.id}</span>
                <Button variant="ghost" size="sm" disabled={add.isPending} onClick={() => add.mutate(row.id)}>
                  <Plus size={12} /> {t("modelAdd")}
                </Button>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* 手填:目录查不到不等于不能用(私有部署、别名)。和目录来的模型在列表里平权。 */}
      <form
        className="flex items-center gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (manualId.trim()) add.mutate(manualId.trim());
        }}
      >
        <Input
          value={manualId}
          placeholder={t("modelManualPlaceholder")}
          className={cn("h-8 flex-1 text-[12px]")}
          onChange={(event) => setManualId(event.target.value)}
        />
        <Button type="submit" variant="outline" size="sm" disabled={!manualId.trim() || add.isPending}>
          {t("modelAdd")}
        </Button>
      </form>
      {vendorLabel && <span className="sr-only">{vendorLabel}</span>}

      {editing && (
        <ModelSettingsDialog
          profileId={profileId}
          modelId={editing}
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
