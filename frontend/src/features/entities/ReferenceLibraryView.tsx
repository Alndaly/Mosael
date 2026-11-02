import React from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, ImageOff, Plus, Search, Sparkles } from "lucide-react";
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
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
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
import { ModelPreviewSettingsButton } from "@/components/generation/ModelPreviewSettingsButton";
import { previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { useCatalogLabels } from "@/features/entities/entityMeta";
import { RadioGroup } from "@/components/ui/radio-group";
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
  const [loaded, setLoaded] = React.useState(false);
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
      {!loaded && <Skeleton aria-hidden data-thumb-loading="" className="absolute inset-0 rounded-none" />}
      <img
        src={item.thumbnail}
        alt=""
        loading="lazy"
        onLoad={() => setLoaded(true)}
        data-loaded={loaded ? "" : undefined}
        className={cn(
          "h-full w-full object-cover opacity-0 transition-opacity duration-160 data-[loaded]:opacity-100 motion-reduce:transition-none",
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
  //: 「用作素材」取哪一张:点详情里的视角来选,默认第一张。「存为资产」每个视角各取一张、按视角挂上 ——
  //: 姿势按镜头机位挑图,只存一张正面的话,斜侧、俯拍的镜头里这个姿势发不出去。
  const [chosenRole, setChosenRole] = React.useState("");
  const role = shown.views.some((view) => view.role === chosenRole) ? chosenRole : (shown.views[0]?.role ?? "");
  const ingest = useMutation({
    mutationFn: (saveEntity: boolean) =>
      ingestReferenceItem(instanceId, {
        workspace_id: workspace.id,
        item_id: shown.id,
        collection: shown.collection,
        ...(saveEntity ? {} : { role }),
        save_entity: saveEntity,
      }),
    onSuccess: (_result, saveEntity) => {
      void invalidateResources(qc, ["assets", "entities"]);
      toast.success(saveEntity ? t("referenceLibrarySaved") : t("referenceLibraryUsed"));
      onClose();
    },
    onError: (error) => toast.error(errorText(error) || t("referenceLibraryUseFailed")),
  });

  const usingMedia = ingest.isPending && ingest.variables === false;
  const savingAsset = ingest.isPending && ingest.variables === true;
  return (
    <ModalShell
      open
      onOpenChange={(open) => !open && !ingest.isPending && onClose()}
      title={itemTitle(shown, locale, settings)}
      footer={
        <>
          <Button variant="outline" loading={usingMedia} disabled={savingAsset} onClick={() => void ingest.mutate(false)}>
            <Plus />{t("referenceLibraryUse")}
          </Button>
          <Button loading={savingAsset} disabled={usingMedia} onClick={() => void ingest.mutate(true)}>
            <Sparkles />{t("referenceLibrarySave")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4" data-reference-item={shown.id}>
        {/* 视角是单选:「用作素材」取选中的那一张。「存为资产」每张都取,不看它。 */}
        <RadioGroup
          aria-label={t("referenceLibraryViews")}
          orientation="horizontal"
          indicator="corner"
          value={role || null}
          onValueChange={setChosenRole}
          options={shown.views.map((view) => ({
            value: view.role,
            label: (
              <span className="grid w-24 gap-1" data-reference-view={view.role}>
                <Thumb item={{ ...shown, thumbnail: view.thumbnail }} className="aspect-[3/4] rounded-md" />
                <span className="text-ui-2xs text-muted-foreground">{labels.role(view.role)}</span>
              </span>
            ),
          }))}
        />
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

/**
 * 图集 / 条目取不出来:照后端那句说为什么(没授权、插件报错、连不上原站……)。此前一律只说「没有加载出来,请重试」,
 * 而最常见的原因 —— 连接还没授予联网权限 —— 重试一百次也一样。
 */
function LibraryFailure({ error }: { error: unknown }) {
  const t = useI18n();
  const fields = rawFailureFields(errorText(error), t("referenceLibraryFailed"));
  return (
    <FailureCard status="failed" title={t("referenceLibraryFailed")} summary={fields.summary} detail={fields.detail} copyText={fields.copyText} />
  );
}

/** 参考库:只读外部图集;浏览只拉缩略图,点「用作素材 / 存为资产」才把单条原图取进工作区。 */
export function ReferenceLibraryView({ workspace, modeSwitch }: { workspace: Workspace; modeSwitch?: React.ReactNode }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [connectionId, setConnectionId] = React.useState("");
  const [collectionId, setCollectionId] = React.useState("");
  const [filters, setFilters] = React.useState<Record<string, string>>({});
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<ReferenceItem | null>(null);
  const sentinelRef = React.useRef<HTMLDivElement>(null);
  const toolbarRef = React.useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = React.useState(false);
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

  //: 滚到底部自动取下一页。IntersectionObserver 用的是视口;这一页的滚动容器在祖先上,但卡片被祖先裁切,
  //: 哨兵进入视口就说明真的滚到了末尾 —— 不用监听某个具体容器的 scrollTop。
  React.useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !items.hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !items.isFetchingNextPage) void items.fetchNextPage();
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [items.hasNextPage, items.isFetchingNextPage, items.fetchNextPage]);

  //: 和素材页同一个吸顶判据:滚动容器一动,筛栏贴顶时就打开底色 / 磨砂。
  React.useEffect(() => {
    const bar = toolbarRef.current;
    const scroller = bar?.closest("[data-entities-scroll]");
    if (!bar || !scroller) return;
    const update = () => setStuck(
      scroller.scrollTop > 0 && bar.getBoundingClientRect().top <= scroller.getBoundingClientRect().top + 1,
    );
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    return () => scroller.removeEventListener("scroll", update);
  }, [connections.data?.length]);

  //: 「有没有参考库」由资产页判(EntitiesView:一个连接都没有、或连接列表取不出来,参考库整块不出现),
  //: 走到这里连接列表一定有 —— 不在这里另画一个空态。
  if (!connections.data) return <Skeleton className="h-48 w-full" />;

  const rows = items.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="grid min-w-0 gap-4" data-reference-library="">
      <div
        ref={toolbarRef}
        data-stuck={stuck}
        className="workspace-sticky sticky top-0 z-20 -mx-6 flex flex-col gap-3 border-b border-divider px-6 py-3 xl:-mx-9 xl:px-9"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3" data-reference-filter-row="">
          <CollectionTabs
            value={activeCollection}
            onChange={(next) => { setCollectionId(next); setFilters({}); }}
            label={t("referenceLibraryCollection")}
            items={(collections.data ?? []).map((one) => ({ value: one.id, label: localized(one.name, locale), count: one.count }))}
          />
          {modeSwitch && <div className="ml-auto">{modeSwitch}</div>}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
          {connections.data.length > 1 && (
            <OptionPicker ariaLabel={t("referenceLibraryConnection")} value={activeConnection} onChange={(value) => { setConnectionId(value); setCollectionId(""); setFilters({}); }} options={connections.data.map((one) => ({ value: one.id, label: one.name }))} className="min-w-40" />
          )}
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <SearchInput
              aria-label={t("referenceLibrarySearch")}
              value={query}
              placeholder={t("referenceLibrarySearch")}
              onChange={(event) => setQuery(event.target.value)}
              className="min-w-40 flex-1"
            />
            {activeCollectionInfo && activeCollectionInfo.filters.map((filter) => (
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
                className="w-auto min-w-28"
              />
            ))}
          </div>
          <div className="flex items-center gap-2 border-divider max-lg:w-full lg:border-l lg:pl-4">
            <ModelPreviewSettingsButton />
          </div>
        </div>
      </div>

      {collections.isError && <LibraryFailure error={collections.error} />}

      {/* 取失败时上面那一条已经说了;这里只管「取到了,但一本图集都没有」—— 一屏只说一次。 */}
      {collections.isSuccess && !activeCollection && (
        <EmptyState icon={<Search />} title={t("referenceLibraryNoItems")} />
      )}

      {!activeCollection ? null : items.isPending ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {Array.from({ length: 12 }).map((_, index) => <Skeleton key={index} className="aspect-[3/4] w-full" />)}
        </div>
      ) : items.isError ? (
        <LibraryFailure error={items.error} />
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
          {items.isFetchingNextPage && (
            <div role="status" aria-busy="true" className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              <span className="sr-only">{t("pageLoading")}</span>
              {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="aspect-[3/4] w-full" />)}
            </div>
          )}
          {items.hasNextPage && <div ref={sentinelRef} className="h-px" aria-hidden />}
        </>
      )}

      {selected && activeConnection && (
        <ItemDetail workspace={workspace} instanceId={activeConnection} item={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
