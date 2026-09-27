import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { toast } from "sonner";

import {
  ENTITY_KINDS,
  createEntity,
  entityKeys,
  listEntities,
  type EntityKind,
  type Workspace,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CARD_GRID, CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { EntityCard } from "@/features/entities/EntityCard";
import { EntityDetail } from "@/features/entities/EntityDetail";
import { entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

/** 深链:`#/entities?entity=<id>`(智能体的 open_view、别处的「在哪里用过」都这么进来)。 */
function entityFromHash(): string | null {
  const query = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get("entity");
}

/**
 * 资产库(ADR 0027):人物 / 场景 / 道具分页签,一张卡片是一个资产的封面。点开是它的详情(参考图墙、描述、
 * 专有字段、变体、在哪里用过)。资产归工作区,不挂项目 —— 同一个角色跨项目用,归类靠标签。
 */
export function EntitiesView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [kind, setKind] = usePersistentTab<EntityKind>("entities-kind", "character", ENTITY_KINDS);
  const [search, setSearch] = React.useState("");
  const [tag, setTag] = React.useState("");
  const [openId, setOpenId] = React.useState<string | null>(entityFromHash);
  const [creating, setCreating] = React.useState(false);

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
  const ofKind = (source ?? []).filter((one) => one.kind === kind);
  const tags = React.useMemo(() => [...new Set(ofKind.flatMap((one) => one.tags))].sort(), [ofKind]);
  const visible = tag ? ofKind.filter((one) => one.tags.includes(tag)) : ofKind;

  const create = useMutation({
    mutationFn: (name: string) => createEntity({ workspace_id: workspace.id, kind, name }),
    onSuccess: (entity) => {
      setCreating(false);
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspace.id) });
      setOpenId(entity.id);
    },
    onError: (error) => toast.error(errorText(error)),
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
  return (
    <div className={STUDIO_PAGE} data-entities-page="">
      <PageHeading
        title={t("navEntities")}
        description={t("entitiesDesc")}
        count={all.data?.length}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            {t("entitiesNew").replace("{kind}", labels.kind(kind))}
          </Button>
        }
      />
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3 border-b border-divider pb-3">
        <CollectionTabs
          value={kind}
          onChange={(next) => {
            setKind(next);
            setTag("");
          }}
          label={t("entitiesKinds")}
          items={ENTITY_KINDS.map((one) => ({
            value: one,
            label: labels.kind(one),
            count: (all.data ?? []).filter((entity) => entity.kind === one).length,
          }))}
        />
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
        {tags.length > 0 && (
          <div role="group" aria-label={t("entityTags")} className="flex flex-wrap gap-1">
            {tags.map((one) => (
              <button
                key={one}
                type="button"
                aria-pressed={tag === one}
                onClick={() => setTag(tag === one ? "" : one)}
                className={cn(
                  "cursor-pointer rounded-full border-0 px-2 py-0.5 text-ui-xs transition-colors",
                  tag === one ? "bg-action text-action-foreground" : "bg-secondary text-muted-foreground hover:text-foreground",
                )}
              >
                {one}
              </button>
            ))}
          </div>
        )}
      </div>

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
          title={
            keyword || tag
              ? t("studioNoMatches")
              : t("entitiesEmptyTitle").replace("{kind}", labels.kind(kind))
          }
          body={keyword || tag ? t("studioNoMatchesHint") : t("entitiesEmptyBody")}
          action={
            keyword || tag ? undefined : (
              <Button onClick={() => setCreating(true)}>
                <Plus />
                {t("entitiesNew").replace("{kind}", labels.kind(kind))}
              </Button>
            )
          }
        />
      ) : (
        <div className={CARD_GRID}>
          {visible.map((entity) => (
            <EntityCard key={entity.id} entity={entity} onOpen={() => setOpenId(entity.id)} />
          ))}
        </div>
      )}

      <RenameDialog
        open={creating}
        title={t("entitiesNew").replace("{kind}", labels.kind(kind))}
        initialValue=""
        confirmLabel={t("entityCreate")}
        pending={create.isPending}
        onCancel={() => setCreating(false)}
        onSubmit={(name) => create.mutate(name)}
      />
    </div>
  );
}
