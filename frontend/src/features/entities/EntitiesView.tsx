import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Search, X } from "lucide-react";
import { toast } from "sonner";

import {
  ENTITY_KINDS,
  createEntity,
  entityKeys,
  listEntities,
  type EntityKind,
  type EntitySummary,
  type Workspace,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { TagFilter } from "@/components/app/TagFilter";
import { RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CARD_GRID, CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { TAG_MATCHES, matchesTags, tagCounts, type TagMatch } from "@/lib/tags";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { EntityGrid, EntitySelectionBar, useEntityCollection } from "@/features/entities/EntityCollection";
import { EntityDetail } from "@/features/entities/EntityDetail";
import { entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

type SortKey = "updated" | "name" | "references";
const SORT_KEYS: readonly SortKey[] = ["updated", "name", "references"];

/** 深链:`#/entities?entity=<id>`(智能体的 open_view、别处的「在哪里用过」都这么进来)。 */
function entityFromHash(): string | null {
  const query = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get("entity");
}

function sortEntities(rows: readonly EntitySummary[], key: SortKey): EntitySummary[] {
  const sorted = [...rows];
  if (key === "name") sorted.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  else if (key === "references") sorted.sort((a, b) => b.reference_count - a.reference_count || b.updated_at.localeCompare(a.updated_at));
  else sorted.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return sorted;
}

/**
 * 资产库(ADR 0027):人物 / 场景 / 道具分页签,一张卡片是一个资产的封面。点开是它的详情。
 * 资产归工作区,不挂项目 —— 同一个角色跨项目用,归类靠标签。
 *
 * 版式和操作照素材库:工具条吸顶(页签、搜索、排序、标签筛选、「选择」),分割线只在有卡片从下面滚过去时
 * 才出现;卡片右键是这一个资产的操作,「选择」进入多选之后批量打标签、删除。
 */
export function EntitiesView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [kind, setKind] = usePersistentTab<EntityKind>("entities-kind", "character", ENTITY_KINDS);
  const [sortKey, setSortKey] = usePersistentTab<SortKey>("entities-sort", "updated", SORT_KEYS);
  const [search, setSearch] = React.useState("");
  const [tagFilter, setTagFilter] = React.useState<string[]>([]);
  const [tagMatch, setTagMatch] = usePersistentTab<TagMatch>("entities-tag-match", "all", TAG_MATCHES);
  const [openId, setOpenId] = React.useState<string | null>(entityFromHash);
  const [creating, setCreating] = React.useState(false);
  const filtersRef = React.useRef<HTMLDivElement>(null);
  const [filtersStuck, setFiltersStuck] = React.useState(false);

  React.useEffect(() => {
    const onHash = () => {
      const id = entityFromHash();
      if (id) setOpenId(id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const all = useQuery({
    queryKey: entityKeys.list(workspace.id),
    queryFn: () => listEntities(workspace.id),
  });
  const keyword = search.trim();
  const found = useQuery({
    queryKey: entityKeys.list(workspace.id, { q: keyword }),
    queryFn: () => listEntities(workspace.id, { q: keyword }),
    enabled: keyword.length > 0,
  });
  const source = keyword ? found.data : all.data;
  const ofKind = React.useMemo(() => (source ?? []).filter((one) => one.kind === kind), [source, kind]);
  const counts = React.useMemo(() => tagCounts(ofKind), [ofKind]);
  const visible = React.useMemo(
    () => sortEntities(ofKind.filter((one) => matchesTags(one, tagFilter, tagMatch)), sortKey),
    [ofKind, tagFilter, tagMatch, sortKey],
  );
  const collection = useEntityCollection(workspace.id, visible, { onOpen: setOpenId });
  const { selectMode, setSelectMode, exit: exitSelectMode } = collection.selection;
  const refresh = () => void qc.invalidateQueries({ queryKey: entityKeys.all(workspace.id) });
  const fail = (error: unknown) => toast.error(errorText(error));

  const create = useMutation({
    mutationFn: (name: string) => createEntity({ workspace_id: workspace.id, kind, name }),
    onSuccess: (entity) => {
      setCreating(false);
      refresh();
      setOpenId(entity.id);
    },
    onError: fail,
  });
  const close = () => {
    setOpenId(null);
    if (entityFromHash()) window.history.replaceState(null, "", "#/entities");
  };

  if (openId) {
    return (
      <div className={STUDIO_PAGE}>
        <EntityDetail workspaceId={workspace.id} entityId={openId} onBack={close} onOpen={setOpenId} />
      </div>
    );
  }

  const KindIcon = entityKindIcon(kind);
  const filtering = Boolean(keyword || tagFilter.length);
  const sortLabel: Record<SortKey, string> = { updated: t("sortUpdated"), name: t("sortName"), references: t("entitiesSortReferences") };

  return (
    <div
      className="flex h-full min-h-0 flex-col items-stretch overflow-auto px-6 pb-7 xl:px-9 xl:pb-8 [&>*]:shrink-0"
      data-entities-page=""
      onScroll={(event) => {
        const filters = filtersRef.current;
        setFiltersStuck(!!filters && event.currentTarget.scrollTop > 0 && filters.getBoundingClientRect().top <= event.currentTarget.getBoundingClientRect().top + 1);
      }}
    >
      <PageHeading
        title={t("navEntities")}
        description={t("entitiesDesc")}
        count={all.data?.length}
        className="py-7 xl:py-8"
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            {t("entitiesNew").replace("{kind}", labels.kind(kind))}
          </Button>
        }
      />

      {/* 吸顶工具条,照素材库:底色和分割线由 .workspace-sticky 按「有没有东西从下面滚过去」淡入淡出
          (data-stuck),静止时不画线;负外边距和外壳的内边距是同一个数。 */}
      <div
        ref={filtersRef}
        data-stuck={filtersStuck}
        className="workspace-sticky sticky top-0 z-20 -mx-6 flex flex-col gap-3 border-b border-divider px-6 py-3 xl:-mx-9 xl:px-9"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
          <CollectionTabs
            value={kind}
            onChange={(next) => {
              setKind(next);
              setTagFilter([]);
            }}
            label={t("entitiesKinds")}
            items={ENTITY_KINDS.map((one) => ({
              value: one,
              label: labels.kind(one),
              count: (all.data ?? []).filter((entity) => entity.kind === one).length,
            }))}
          />
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <div className="relative min-w-40 flex-1">
              <Search size={16} className="pointer-events-none absolute left-3 top-3 text-muted-foreground" />
              <Input
                aria-label={t("entitiesSearch")}
                className="border-border bg-control pl-9"
                value={search}
                placeholder={t("entitiesSearch")}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
              <SelectTrigger className="w-auto min-w-32 border-border bg-control" aria-label={t("entitiesSort")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-w-none">
                {SORT_KEYS.map((one) => (
                  <SelectItem key={one} value={one}>
                    {sortLabel[one]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {counts.size > 0 && (
              <TagFilter counts={counts} value={tagFilter} onChange={setTagFilter} match={tagMatch} onMatchChange={setTagMatch} />
            )}
          </div>
          <div className="flex items-center gap-2 border-divider max-lg:w-full lg:border-l lg:pl-4">
            <Button variant="outline" className="ml-auto" aria-pressed={selectMode} onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}>
              {selectMode ? <X /> : <Check />}
              {selectMode ? t("cancel") : t("mediaSelectMode")}
            </Button>
          </div>
        </div>
        <EntitySelectionBar collection={collection} rows={visible} className="border-t border-divider pt-3" />
      </div>

      <div className="pt-5">
        {all.isPending ? (
          <div role="status" aria-busy="true" className={CARD_GRID}>
            <span className="sr-only">{t("pageLoading")}</span>
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="grid gap-3" aria-hidden="true">
                <Skeleton className="aspect-[4/5] w-full rounded-lg" />
                <Skeleton className="h-4 w-3/5" />
              </div>
            ))}
          </div>
        ) : all.isError ? (
          <EmptyState
            icon={<KindIcon />}
            title={t("pageLoadError")}
            body={all.error.message}
            action={<Button variant="secondary" onClick={() => void all.refetch()}>{t("retry")}</Button>}
          />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<KindIcon size={22} />}
            title={filtering ? t("studioNoMatches") : t("entitiesEmptyTitle").replace("{kind}", labels.kind(kind))}
            body={filtering ? t("studioNoMatchesHint") : t(`entitiesEmptyBody_${kind}`)}
            action={
              filtering ? undefined : (
                <Button onClick={() => setCreating(true)}>
                  <Plus />
                  {t("entitiesNew").replace("{kind}", labels.kind(kind))}
                </Button>
              )
            }
          />
        ) : (
          <EntityGrid collection={collection} rows={visible} className={CARD_GRID} />
        )}
      </div>

      <RenameDialog
        open={creating}
        title={t("entitiesNew").replace("{kind}", labels.kind(kind))}
        initialValue=""
        confirmLabel={t("entityCreate")}
        pending={create.isPending}
        onCancel={() => setCreating(false)}
        onSubmit={(name) => create.mutate(name)}
      />
      {collection.dialogs}
    </div>
  );
}
