import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Layers } from "lucide-react";

import { entityKeys, listEntities, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { EntityThumb } from "@/features/entities/EntityMention";
import { entityDisplayName, useCatalogLabels } from "@/features/entities/entityMeta";

/**
 * 从资产库挑一个资产(含变体)。画板「引用 · 资产」、素材库右键「设为某个资产的参考图…」都是这一个弹窗 ——
 * 和挑笔记、挑 3D 场景同一个版式(PickListDialog)。资产是「搭出来的」,一个工作区几十到几百个,筛选在前端做。
 */
export function EntityPickerDialog({
  workspaceId,
  open,
  onOpenChange,
  onPick,
  title,
  description,
}: {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (entity: EntitySummary) => void;
  title?: string;
  description?: string;
}) {
  const t = useI18n();
  const labels = useCatalogLabels(open);
  const [search, setSearch] = React.useState("");
  const entities = useQuery({
    queryKey: entityKeys.list(workspaceId, { includeVariants: true }),
    queryFn: () => listEntities(workspaceId, { includeVariants: true }),
    enabled: open,
  });
  const keyword = search.trim().toLowerCase();
  const matches = React.useMemo(
    () => (entities.data ?? []).filter((one) => !keyword || entityDisplayName(one).toLowerCase().includes(keyword)),
    [entities.data, keyword],
  );
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title ?? t("entityPickTitle")}
      description={description ?? t("entityPickHint")}
      searchLabel={t("entityPickSearch")}
      query={search}
      onQueryChange={setSearch}
      items={matches}
      itemKey={(one) => one.id}
      row={(one) => ({
        lead: <EntityThumb entity={one} />,
        title: entityDisplayName(one),
        subtitle: t("entityRefCount").replace("{n}", String(one.reference_count)),
        meta: labels.kind(one.kind),
      })}
      onPick={(one) => {
        onPick(one);
        onOpenChange(false);
      }}
      pending={entities.isPending}
      error={entities.isError ? entities.error.message : null}
      onRetry={() => void entities.refetch()}
      empty={{
        icon: <Layers size={24} strokeWidth={1.5} />,
        text: t(entities.data?.length ? "entityPickNoMatches" : "entityPickNone"),
      }}
    />
  );
}
