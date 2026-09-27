import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Layers, ListChecks, Pencil, Tag, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { createVariant, deleteEntity, entityKeys, updateEntity, type EntitySummary } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { TagsDialog } from "@/components/app/TagsDialog";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { cn } from "@/lib/utils";
import { EntityCard } from "@/features/entities/EntityCard";

/**
 * 一组资产卡片的操作 —— 资产库列表和详情里的「变体」是**同一套**:右键(打开、重命名、编辑标签、新建变体、删除)、
 * 「选择」之后批量打标签和删除。两处各写一份的话,一处加了能力另一处就缺(变体页签此前正是这样:不能右键、不能多选)。
 *
 * 用法:`useEntityCollection(工作区, 这一组卡片)` 拿到多选状态和动作,`<EntityGrid>` 画卡片,
 * `<EntitySelectionBar>` 是选中之后那一排按钮,`dialogs` 放在页面里任何地方。
 */
export function useEntityCollection(
  workspaceId: string,
  rows: readonly EntitySummary[],
  { onOpen }: { onOpen: (id: string) => void },
) {
  const t = useI18n();
  const qc = useQueryClient();
  const idOf = React.useCallback((one: EntitySummary) => one.id, []);
  const selection = useMultiSelect(rows, idOf);
  const [renaming, setRenaming] = React.useState<EntitySummary | null>(null);
  const [editingTags, setEditingTags] = React.useState<EntitySummary | null>(null);
  const [variantOf, setVariantOf] = React.useState<EntitySummary | null>(null);
  const [deleting, setDeleting] = React.useState<EntitySummary[] | null>(null);
  const [batchTagging, setBatchTagging] = React.useState(false);
  const selected = rows.filter((one) => selection.selectedIds.has(one.id));
  //: 列表、详情(变体在母体的详情里)都在这一个前缀下,一次刷全。
  const refresh = () => void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
  const fail = (error: unknown) => toast.error(errorText(error));

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateEntity(id, { name }),
    onSuccess: () => {
      setRenaming(null);
      refresh();
    },
    onError: fail,
  });
  const saveTags = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => updateEntity(id, { tags }),
    onSuccess: () => {
      setEditingTags(null);
      refresh();
    },
    onError: fail,
  });
  const batchAddTags = useMutation({
    //: 加到每一个选中的资产上,已有的标签留着(和素材库的「打标签」同一个意思)。
    mutationFn: async (tags: string[]) => {
      for (const one of selected) await updateEntity(one.id, { tags: [...new Set([...one.tags, ...tags])] });
    },
    onSuccess: () => {
      setBatchTagging(false);
      refresh();
    },
    onError: fail,
  });
  const variant = useMutation({
    mutationFn: ({ parent, name }: { parent: EntitySummary; name: string }) => createVariant(parent.id, { name }),
    onSuccess: (made) => {
      setVariantOf(null);
      refresh();
      onOpen(made.id);
    },
    onError: fail,
  });
  const remove = useMutation({
    //: 有变体的连变体一起删(确认框里写明了);素材不动。
    mutationFn: async (targets: EntitySummary[]) => {
      for (const one of targets) await deleteEntity(one.id, one.variant_count > 0);
    },
    onSuccess: () => {
      setDeleting(null);
      selection.exit();
      refresh();
    },
    onError: fail,
  });

  const withVariants = (deleting ?? []).reduce((sum, one) => sum + one.variant_count, 0);
  const dialogs = (
    <>
      <RenameDialog
        open={renaming !== null}
        title={t("rename")}
        initialValue={renaming?.name ?? ""}
        pending={rename.isPending}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <RenameDialog
        open={variantOf !== null}
        title={t("entityVariantNew")}
        initialValue=""
        confirmLabel={t("entityCreate")}
        pending={variant.isPending}
        onCancel={() => setVariantOf(null)}
        onSubmit={(name) => variantOf && variant.mutate({ parent: variantOf, name })}
      />
      <TagsDialog
        open={editingTags !== null}
        title={t("editTags")}
        initialTags={editingTags?.tags ?? []}
        onCancel={() => setEditingTags(null)}
        onSubmit={(tags) => editingTags && saveTags.mutate({ id: editingTags.id, tags })}
      />
      <TagsDialog
        open={batchTagging}
        title={t("addTags")}
        body={t("entitiesAddTagsBody")}
        initialTags={[]}
        onCancel={() => setBatchTagging(false)}
        onSubmit={(tags) => tags.length > 0 && batchAddTags.mutate(tags)}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={
          deleting?.length === 1
            ? t("entityDeleteTitle").replace("{name}", deleting[0].name)
            : t("entitiesDeleteManyTitle").replace("{n}", String(deleting?.length ?? 0))
        }
        body={withVariants > 0 ? t("entityDeleteWithVariants").replace("{n}", String(withVariants)) : t("entityDeleteBody")}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  );

  return {
    selection,
    selected,
    dialogs,
    actions: {
      open: onOpen,
      rename: setRenaming,
      editTags: setEditingTags,
      addVariant: setVariantOf,
      remove: (targets: EntitySummary[]) => setDeleting(targets),
      tagSelected: () => setBatchTagging(true),
    },
  };
}

export type EntityCollection = ReturnType<typeof useEntityCollection>;

/** 一格一个资产:右键是它自己的操作;选择模式下点卡片是选中,不是打开。 */
export function EntityGrid({
  collection,
  rows,
  className,
}: {
  collection: EntityCollection;
  rows: readonly EntitySummary[];
  className: string;
}) {
  const t = useI18n();
  const { selection, actions } = collection;
  return (
    <div className={className}>
      {rows.map((entity) => (
        <ContextMenu key={entity.id}>
          <ContextMenuTrigger asChild>
            <div className="relative min-w-0" data-entity-tile={entity.id}>
              <EntityCard
                entity={entity}
                selected={selection.selectMode && selection.selectedIds.has(entity.id)}
                onOpen={() => (selection.selectMode ? selection.toggle(entity.id) : actions.open(entity.id))}
              />
              {selection.selectMode && <SelectionCheck selected={selection.selectedIds.has(entity.id)} />}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuItem onSelect={() => actions.open(entity.id)}>
              <FolderOpen size={14} />
              {t("entitiesOpen")}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => actions.rename(entity)}>
              <Pencil size={14} />
              {t("rename")}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => actions.editTags(entity)}>
              <Tag size={14} />
              {t("editTags")}
            </ContextMenuItem>
            {/* 变体下面不再挂变体。 */}
            {!entity.parent_id && (
              <ContextMenuItem onSelect={() => actions.addVariant(entity)}>
                <Layers size={14} />
                {t("entityVariantNew")}
              </ContextMenuItem>
            )}
            <ContextMenuSeparator />
            <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => actions.remove([entity])}>
              <Trash2 size={14} />
              {t("delete")}
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
      ))}
    </div>
  );
}

/** 选择模式下那一排:已选几个、全选、打标签、删除。 */
export function EntitySelectionBar({
  collection,
  rows,
  className,
}: {
  collection: EntityCollection;
  rows: readonly EntitySummary[];
  className?: string;
}) {
  const t = useI18n();
  const { selection, selected, actions } = collection;
  if (!selection.selectMode) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)} role="group" aria-label={t("mediaSelectMode")}>
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {t("mediaSelectedCount").replace("{n}", String(selection.selectedIds.size))}
      </span>
      <Button variant="outline" onClick={() => selection.selectAll(rows)}>
        <ListChecks size={13} />
        {selection.allSelected(rows) ? t("mediaDeselectAll") : t("mediaSelectAll")}
      </Button>
      <Button variant="outline" disabled={selected.length === 0} onClick={actions.tagSelected}>
        <Tag size={13} />
        {t("addTags")}
      </Button>
      <Button
        variant="outline"
        className="hover:border-destructive/50 hover:text-destructive"
        disabled={selected.length === 0}
        onClick={() => actions.remove(selected)}
      >
        <Trash2 size={13} />
        {t("delete")}
      </Button>
    </div>
  );
}
