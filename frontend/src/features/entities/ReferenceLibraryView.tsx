import React from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, ImageOff, Plug, Plus, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";

import {
  getReferenceItem,
  listReferenceCollections,
  listReferenceConnections,
  searchReferenceItems,
  ingestReferenceItem,
  type ReferenceItem,
  type Workspace,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { referenceKeys } from "@/api/queryKeys";
import { invalidateResources } from "@/api/resourceKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CollectionTabs } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { OptionPicker } from "@/components/ui/option-picker";
import { Truncate } from "@/components/ui/truncate";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { useCatalogLabels } from "@/features/entities/entityMeta";
import { cn } from "@/lib/utils";

function localized(value: Record<string, string>, locale: string): string {
  return value[locale.startsWith("zh") ? "zh" : "en"] || value.zh || value.en || Object.values(value)[0] || "—";
}

/** NSFW 模糊 / 隐藏时只显示条目编号;名称里的露骨措辞也走同一档(ADR 0091 §3/§4)。 */
function itemTitle(item: ReferenceItem, locale: string, settings: ReturnType<typeof useModelPreviewSettings>[0]): string {
  return previewTreatment(settings, item.nsfw) === "clear" ? localized(item.name, locale) : item.id;
}

function Thumb({ item, className }: { item: ReferenceItem; className?: string }) {
  const [settings] = useModelPreviewSettings();
  const treatment = previewTreatment(settings, item.nsfw);
  if (!item.thumbnail || treatment === "hidden") {
    return (
      <span className={cn("grid place-items-center bg-secondary text-muted-foreground", className)} data-hidden-preview="">
        <ImageOff size={18} />
      </span>
    );
  }
  return (
    <span className={cn("relative block overflow-hidden bg-secondary", className)}>
      <img
        src={item.thumbnail}
        alt=""
        loading="lazy"
        className={cn(
          "h-full w-full object-cover",
          treatment === "light" && "blur-[2px]",
          treatment === "heavy" && "blur-md",
        )}
      />
      {item.nsfw && <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold text-white">NSFW</span>}
    </span>
  );
}

function ItemDetail({
  workspace,
  instanceId,
  item,
  onClose,
}: {
  workspace: Workspace;
  instanceId: string;
  item: ReferenceItem;
  onClose: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [settings] = useModelPreviewSettings();
  //: 机位名(正面、斜侧、俯拍……)读资产库的词表 —— 插件交的是角度的键,不是给人看的字。
  const labels = useCatalogLabels();
  const detail = useQuery({
    queryKey: referenceKeys.item(instanceId, item.id),
    queryFn: () => getReferenceItem(instanceId, item.id, item.collection),
  });
  const shown = detail.data ?? item;
  const ingest = useMutation({
    mutationFn: (saveEntity: boolean) =>
      ingestReferenceItem(instanceId, {
        workspace_id: workspace.id,
        item_id: shown.id,
        collection: shown.collection,
        save_entity: saveEntity,
      }),
    onSuccess: (_result, saveEntity) => {
      void invalidateResources(qc, ["assets", "entities"]);
      toast.success(saveEntity ? t("referenceLibrarySaved") : t("referenceLibraryUsed"));
      onClose();
    },
    onError: (error) => toast.error(errorText(error) || t("referenceLibraryUseFailed")),
  });

  return (
    <ModalShell
      open
      onOpenChange={(open) => !open && !ingest.isPending && onClose()}
      title={itemTitle(shown, locale, settings)}
      footer={
        <>
          <Button variant="outline" loading={ingest.isPending} onClick={() => void ingest.mutate(false)}>
            <Plus />{t("referenceLibraryUse")}
          </Button>
          <Button loading={ingest.isPending} onClick={() => void ingest.mutate(true)}>
            <Sparkles />{t("referenceLibrarySave")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4" data-reference-item={shown.id}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {shown.views.map((view) => (
            <figure key={`${view.role}-${view.thumbnail}`} className="m-0 grid gap-1">
              <Thumb item={{ ...shown, thumbnail: view.thumbnail }} className="aspect-[3/4] rounded-md" />
              <figcaption className="text-ui-2xs text-muted-foreground">{labels.role(view.role)}</figcaption>
            </figure>
          ))}
        </div>
        {shown.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {shown.tags.map((tag) => <span key={tag} className="rounded-full bg-secondary px-2 py-0.5 text-ui-2xs">{tag}</span>)}
          </div>
        )}
        <div className="grid gap-1 rounded-md border border-border bg-card px-3 py-2 text-ui-xs text-muted-foreground">
          <strong className="text-foreground">{t("referenceLibraryProvenance")}</strong>
          {shown.provenance.author && <span>{shown.provenance.author}</span>}
          {shown.provenance.license && <span>{shown.provenance.license}</span>}
          {shown.provenance.url && (
            <a href={shown.provenance.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              <ExternalLink size={12} />{shown.provenance.url}
            </a>
          )}
          <span>{t("referenceLibraryExternal")}</span>
        </div>
      </div>
    </ModalShell>
  );
}

/** 参考库:只读外部图集;浏览只拉缩略图,点「用作素材 / 存为资产」才把单条原图取进工作区。 */
export function ReferenceLibraryView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [connectionId, setConnectionId] = React.useState("");
  const [collectionId, setCollectionId] = React.useState("");
  const [filters, setFilters] = React.useState<Record<string, string>>({});
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<ReferenceItem | null>(null);
  const [settings] = useModelPreviewSettings();

  const connections = useQuery({ queryKey: referenceKeys.connections(), queryFn: listReferenceConnections });
  const activeConnection = connectionId || connections.data?.[0]?.id || "";
  const collections = useQuery({
    queryKey: referenceKeys.collections(activeConnection),
    queryFn: () => listReferenceCollections(activeConnection),
    enabled: Boolean(activeConnection),
  });
  const activeCollection = collectionId || collections.data?.[0]?.id || "";
  const activeCollectionInfo = collections.data?.find((one) => one.id === activeCollection);
  const items = useInfiniteQuery({
    queryKey: referenceKeys.search(activeConnection, activeCollection, query.trim(), filters),
    queryFn: ({ pageParam }) => searchReferenceItems(activeConnection, {
      collection: activeCollection, q: query.trim(), filters, cursor: pageParam, limit: 40,
    }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: Boolean(activeConnection && activeCollection),
  });

  if (connections.isPending) return <Skeleton className="h-48 w-full" />;
  if (connections.isError) return <EmptyState icon={<ImageOff />} title={t("referenceLibraryFailed")} />;
  if (!connections.data?.length) {
    //: PoseAtlas 随应用内置(ADR 0091 §7),但它有配置、要联网权限,不会自动建连接 —— 空态直接指到插件页去接一下。
    return (
      <EmptyState
        icon={<Sparkles />}
        title={t("referenceLibraryNone")}
        body={t("referenceLibraryNoneHint")}
        action={<Button asChild><a href="#/plugins"><Plug />{t("capabilityGoPlugins")}</a></Button>}
      />
    );
  }

  const rows = items.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="grid min-w-0 gap-4" data-reference-library="">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {connections.data.length > 1 && (
          <OptionPicker ariaLabel={t("referenceLibraryConnection")} value={activeConnection} onChange={(value) => { setConnectionId(value); setCollectionId(""); setFilters({}); }} options={connections.data.map((one) => ({ value: one.id, label: one.name }))} className="min-w-40" />
        )}
        <SearchInput
          aria-label={t("referenceLibrarySearch")}
          value={query}
          placeholder={t("referenceLibrarySearch")}
          onChange={(event) => setQuery(event.target.value)}
          className="min-w-52 flex-1"
        />
      </div>

      <CollectionTabs
        value={activeCollection}
        onChange={(next) => { setCollectionId(next); setFilters({}); }}
        label={t("referenceLibraryCollection")}
        items={(collections.data ?? []).map((one) => ({ value: one.id, label: localized(one.name, locale), count: one.count }))}
      />

      {collections.isError && <EmptyState icon={<ImageOff />} title={t("referenceLibraryFailed")} />}

      {/* 取失败时上面那一条已经说了;这里只管「取到了,但一本图集都没有」—— 一屏只说一次。 */}
      {collections.isSuccess && !activeCollection && (
        <EmptyState icon={<Search />} title={t("referenceLibraryNoItems")} />
      )}

      {activeCollectionInfo && activeCollectionInfo.filters.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {activeCollectionInfo.filters.map((filter) => (
            <OptionPicker
              key={filter.key}
              ariaLabel={filter.label}
              value={filters[filter.key] ?? "__all"}
              onChange={(value) => setFilters((current) => {
                const next = { ...current };
                if (value === "__all") delete next[filter.key];
                else next[filter.key] = value;
                return next;
              })}
              options={[{ value: "__all", label: filter.label }, ...filter.values]}
              className="w-44"
            />
          ))}
        </div>
      )}

      {!activeCollection ? null : items.isPending ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {Array.from({ length: 12 }).map((_, index) => <Skeleton key={index} className="aspect-[3/4] w-full" />)}
        </div>
      ) : items.isError ? (
        <EmptyState icon={<ImageOff />} title={t("referenceLibraryFailed")} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Search />} title={t("referenceLibraryNoItems")} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {rows.map((item) => (
              <button
                key={`${item.collection}-${item.id}`}
                type="button"
                onClick={() => setSelected(item)}
                className="group grid min-w-0 gap-1.5 rounded-md border border-border bg-card p-1.5 text-left transition-colors hover:border-primary/50"
              >
                <Thumb item={item} className="aspect-[3/4] rounded-sm" />
                <Truncate className="text-ui-xs">{itemTitle(item, locale, settings)}</Truncate>
              </button>
            ))}
          </div>
          {items.hasNextPage && (
            <Button variant="outline" className="mx-auto" loading={items.isFetchingNextPage} onClick={() => void items.fetchNextPage()}>
              {t("referenceLibraryLoadMore")}
            </Button>
          )}
        </>
      )}

      {selected && activeConnection && (
        <ItemDetail workspace={workspace} instanceId={activeConnection} item={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
