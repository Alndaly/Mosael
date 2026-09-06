import { ACTION_MENU } from "@/components/ui/floating";
import { PageHeading, CollectionTabs } from "@/components/layout/StudioPage";
import { LayoutGrid, List, MoreHorizontal, Search } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger, PopoverClose } from "@/components/ui/popover";
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDot, Columns2, Download, FileAudio, FileImage, FileVideo, FolderOpen, ImagePlus, Link2, ListChecks, Loader2, Pencil, Tag, Trash2, Upload, X } from "lucide-react";

import { api, assetThumbnailUrl, convertVideoToGif, deleteAsset, importAsset, renameAsset, setAssetTags, type Asset, type Workspace } from "@/api/client";
import { UrlImportDialog } from "@/features/media/UrlImportDialog";
import { saveAssetToDisk } from "@/lib/download";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
import { toast } from "sonner";
import { useI18n } from "@/app/preferences";
import { AssetCompareView } from "@/features/media/AssetCompareView";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { useRecorder } from "@/features/media/RecordingProvider";
import { AssetPreviewModal } from "@/features/media/AssetPreviewModal";
import { MediaTagFilter } from "./MediaTagFilter";
import { TagsDialog } from "@/features/media/TagsDialog";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { usePersistentSelection, usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

const KIND_FILTERS = ["all", "video", "audio", "image"] as const;
type KindFilter = (typeof KIND_FILTERS)[number];

/** OpenAPI 里 tags 带默认值所以是可选字段;统一成数组再用。 */
const assetTags = (asset: Asset): string[] => asset.tags ?? [];

const SORT_KEYS = ["created", "updated", "name", "duration"] as const;
type SortKey = (typeof SORT_KEYS)[number];

function compareAssets(a: Asset, b: Asset, key: SortKey): number {
  switch (key) {
    case "name":
      return a.name.localeCompare(b.name, "zh-CN");
    case "duration":
      return (Number(b.media_info.duration) || 0) - (Number(a.media_info.duration) || 0);
    case "updated":
      return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
    default:
      return (b.created_at ?? "").localeCompare(a.created_at ?? "");
  }
}

/**
 * 素材库 —— **工作区级**资源池。素材归属工作区(Asset.workspace_id 必填;project_id 可空,
 * 删项目只置空),所以这一页不带项目语境:列出整个工作区的素材,导入也不挂项目。
 * 需要"属于某个项目"的素材,从剪辑页导入。
 */
export function MediaLibraryView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { openRecorder } = useRecorder();
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [previewing, setPreviewing] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [editingTags, setEditingTags] = React.useState<Asset | null>(null);
  // 筛选和排序是**这个人怎么用素材库**的一部分,不是这一刻的临时值 —— 切走再回来不该重置。
  // 搜索词是另一回事:它是"我此刻在找什么",留着反而会让人以为库里只有这几条。
  const [kindFilter, setKindFilter] = usePersistentTab<KindFilter>("media-kind", "all", KIND_FILTERS);
  const [search, setSearch] = React.useState("");
  const [display, setDisplay] = usePersistentTab<"grid" | "list">("media-display", "grid", ["grid", "list"]);
  const [sortKey, setSortKey] = usePersistentTab<SortKey>("media-sort", "created", SORT_KEYS);
  const [comparing, setComparing] = React.useState(false);
  const [batchTagging, setBatchTagging] = React.useState(false);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const [urlImportOpen, setUrlImportOpen] = React.useState(false);
  const importInputRef = React.useRef<HTMLInputElement>(null);
  const filtersRef = React.useRef<HTMLDivElement>(null);
  const [filtersStuck, setFiltersStuck] = React.useState(false);
  const [actionMenuId, setActionMenuId] = React.useState<string | null>(null);

  const assets = useQuery({
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
  });
  // 多选的状态机是共用的(见 lib/useMultiSelect)—— 素材、发布记录、工作流三处同一份。
  const { selectMode, setSelectMode, selectedIds, toggle: toggleSelected, selectAll, allSelected, clear: clearSelection, exit: exitSelectMode } =
    useMultiSelect(assets.data ?? [], (asset) => asset.id);
  /** 选中项里能参与对比的(只有图片)。 */
  const comparable = React.useMemo(
    () => (assets.data ?? []).filter((asset) => selectedIds.has(asset.id) && asset.kind === "image"),
    [assets.data, selectedIds],
  );
  const refresh = () => qc.invalidateQueries({ queryKey: ["assets"] });

  // Cmd+K 面板选中素材后跳转到本页并直接打开预览。
  React.useEffect(() => {
    const onOpenAsset = (event: Event) => {
      const assetId = (event as CustomEvent<string>).detail;
      const asset = (assets.data ?? []).find((item) => item.id === assetId);
      if (!asset) return;
      // 统一先进详情卡(图片也一样),要看大图再从卡里点开;避免图片直接跳全屏、看不到数据。
      setPreviewing(asset);
    };
    window.addEventListener("mosael:open-asset", onOpenAsset);
    return () => window.removeEventListener("mosael:open-asset", onOpenAsset);
  }, [assets.data]);

  const uploadAsset = useMutation({
    // 工作区级导入:不挂 project_id,该工作区下所有项目都能用。
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, file }),
    onSuccess: refresh,
  });
  const convertGif = useMutation({
    mutationFn: (assetId: string) => convertVideoToGif(assetId),
    onSuccess: () => toast.success(t("assetConvertGifQueued")),
    onError: (error: Error) => toast.error(error.message),
  });
  // 从访达直接拖进来。**逐个传而不是并发** —— 一次拖十个视频,并发会把带宽和后端的
  // 转码队列同时打满,而用户看到的是十个都卡着不动。
  const dropUpload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await importAsset({ workspaceId: workspace.id, file });
      }
      return files.length;
    },
    onSuccess: (count) => {
      refresh();
      toast.success(t("mediaDropped").replace("{n}", String(count)));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const drop = useFileDrop((files) => dropUpload.mutate(files), isMediaFile);
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameAsset(id, name),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setRenaming(null);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => {
      setDeleteError(null);
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
    onError: (error) => setDeleteError(String((error as Error).message)),
  });
  const saveTags = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => setAssetTags(id, tags),
    onSuccess: () => {
      setEditingTags(null);
      void refresh();
    },
  });
  // 批量打标:并集合并到每个选中素材上,已有标签保留。
  const batchAddTags = useMutation({
    mutationFn: async (tags: string[]) => {
      const targets = (assets.data ?? []).filter((asset) => selectedIds.has(asset.id));
      await Promise.all(
        targets.map((asset) => {
          const merged = [...assetTags(asset)];
          for (const tag of tags) if (!merged.includes(tag)) merged.push(tag);
          return setAssetTags(asset.id, merged);
        }),
      );
    },
    onSuccess: () => {
      setBatchTagging(false);
      void refresh();
    },
  });
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 时间线占用中的素材会被后端 422 拒绝;逐个尝试,失败的留下并提示。
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deleteAsset(id);
        } catch (error) {
          const asset = assets.data?.find((item) => item.id === id);
          failures.push(`${asset?.name ?? id}: ${String((error as Error).message)}`);
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setBatchDeleting(false);
      clearSelection();
      if (failures.length > 0) setDeleteError(failures.join("\n"));
      void refresh();
    },
  });

  const allTags = React.useMemo(() => {
    const set = new Set<string>();
    for (const asset of assets.data ?? []) for (const tag of assetTags(asset)) set.add(tag);
    return [...set].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [assets.data]);

  // 标签筛选同理。用 selection 而不是 tab:合法值是**动态的**(标签会被删),存着一个已经不存在
  // 的标签时当作没筛 —— 否则素材库会空得莫名其妙。
  const [tagFilter, setTagFilter] = usePersistentSelection(
    "media-tag",
    assets.data === undefined ? undefined : allTags,
  );

  const visible = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    const matched = (assets.data ?? []).filter(
      (asset) =>
        (kindFilter === "all" || asset.kind === kindFilter) &&
        (tagFilter === null || assetTags(asset).includes(tagFilter)) &&
        (query === "" ||
          asset.name.toLowerCase().includes(query) ||
          assetTags(asset).some((tag) => tag.toLowerCase().includes(query))),
    );
    return [...matched].sort((a, b) => compareAssets(a, b, sortKey));
  }, [assets.data, kindFilter, tagFilter, search, sortKey]);


  const kindLabel: Record<KindFilter, string> = {
    all: t("kindAll"),
    video: t("kindVideo"),
    audio: t("kindAudio"),
    image: t("kindImage"),
  };

  return (
    // 两层:外层不滚,只做定位上下文;里层是滚动区。遮罩挂在**外层**上 ——
    // 挂在滚动容器里的话,absolute 会跟着内容一起滚走,滚到一半松手时提示已经在屏幕外了。
    <div className="relative h-full min-h-0" {...drop.handlers}>
      {/* inset-0 一点不留:留边就会在四角露出没被盖住的缝。落点是整块区域,不是某个方框。 */}
      {(drop.active || dropUpload.isPending) && (
        <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
          <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
            {dropUpload.isPending ? (
              <>
                <Loader2 size={20} className="animate-mosael-spin" />
                {t("mediaDropUploading")}
              </>
            ) : (
              <>
                <Upload size={20} />
                {t("mediaDropHint")}
              </>
            )}
          </span>
        </div>
      )}
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto px-6 pb-7 xl:px-9 xl:pb-8 [&>*]:shrink-0"
        onScroll={(event) => {
          const filters = filtersRef.current;
          setFiltersStuck(!!filters && event.currentTarget.scrollTop > 0 && filters.getBoundingClientRect().top <= event.currentTarget.getBoundingClientRect().top + 1);
        }}
      >
      <PageHeading title={t("navMedia")} description={t("studioMediaDesc")} count={assets.data?.length} className="py-7 xl:py-8" actions={<>
              <input
                ref={importInputRef}
                type="file"
                accept="video/*,audio/*,image/*"
                className="hidden"
                disabled={uploadAsset.isPending}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) uploadAsset.mutate(file);
                  event.currentTarget.value = "";
                }}
              />
              <Button size="default" loading={uploadAsset.isPending} onClick={() => importInputRef.current?.click()}>
                <ImagePlus />{t("import")}
              </Button>
              <Button variant="outline" size="default" onClick={() => setUrlImportOpen(true)}>
                <Link2 size={13} /> {t("urlImport")}
              </Button>
              <Button variant="outline" size="default" onClick={() => openRecorder()}>
                <CircleDot size={13} /> {t("record")}
              </Button>
      </>} />
      {/* 顶部工具条 + 标签筛选 sticky 吸顶:滚动素材网格时保持可见。顶部内边距放在本 sticky 头上
          (滚动容器不留 pt),吸顶时才能严丝合缝贴顶、不露出上一行卡片;-mx 铺满宽度,bg 盖住滚上来的卡片。 */}
      {/* 负外边距和外壳的内边距**是同一个数**:它靠 -mx 把自己拉到容器边缘,好让 sticky 时的
          底色铺满整宽。外壳从 px-3.5 收到 px-2 之后这层耦合就断了 —— 工具条比容器宽出 12px,
          整页于是能左右滚(真机)。两个数写在一起,下次改 padding 时才看得见要一起改。 */}
      {(!assets.isSuccess || (assets.data ?? []).length > 0) && (
        <div ref={filtersRef} data-stuck={filtersStuck} className="workspace-sticky sticky top-0 z-20 -mx-6 flex flex-col gap-3 border-b border-divider bg-background px-6 py-3 xl:-mx-9 xl:px-9">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
            <CollectionTabs value={kindFilter} onChange={setKindFilter} label={t("mediaKindGroup")} items={KIND_FILTERS.map(kind => ({ value: kind, label: kindLabel[kind], count: assets.data?.filter(asset => kind === "all" || asset.kind === kind).length }))} />
            <div className="flex items-center gap-2">
              <div role="group" className="flex gap-1" aria-label={t("studioGridView")}>
                <Button variant="outline" className={cn("px-3", display === "grid" && "border-primary/40 bg-accent text-primary")} aria-label={t("studioGridView")} aria-pressed={display === "grid"} onClick={() => setDisplay("grid")}><LayoutGrid /></Button>
                <Button variant="outline" className={cn("px-3", display === "list" && "border-primary/40 bg-accent text-primary")} aria-label={t("studioListView")} aria-pressed={display === "list"} onClick={() => setDisplay("list")}><List /></Button>
              </div>
              <Button variant="outline" aria-pressed={selectMode} onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}>
                {selectMode ? <X /> : <Check />}{selectMode ? t("cancel") : t("mediaSelectMode")}
              </Button>
            </div>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2" data-media-filter-row>
            <div className="relative min-w-40 flex-1">
              <Search size={16} className="pointer-events-none absolute left-3 top-3 text-muted-foreground" />
              <Input aria-label={t("searchAssets")} className="border-border bg-control pl-9" value={search} placeholder={t("searchAssets")} onChange={(event) => setSearch(event.target.value)} />
            </div>
            <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
              <SelectTrigger className="w-auto min-w-36 border-border bg-control" aria-label={t("sortNewest")}><SelectValue /></SelectTrigger>
              <SelectContent className="max-w-none">
                <SelectItem value="created">{t("sortNewest")}</SelectItem>
                <SelectItem value="updated">{t("sortUpdated")}</SelectItem>
                <SelectItem value="name">{t("sortName")}</SelectItem>
                <SelectItem value="duration">{t("sortDuration")}</SelectItem>
              </SelectContent>
            </Select>
            {allTags.length > 0 && <MediaTagFilter tags={allTags} value={tagFilter} onChange={setTagFilter} />}
          </div>
          {selectMode && <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-3" role="group" aria-label={t("mediaSelectMode")}>

                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                    {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
                  </span>
                  <Button variant="outline" size="default" onClick={() => selectAll(visible)}>
                    <ListChecks size={13} />{" "}
                    {allSelected(visible) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                  </Button>
                  {/* 对比只对图片有意义;视频要同步播放/逐帧,是另一套设计。少于两张时禁用并说明原因。 */}
                  <Button
                    variant="outline"
                    size="default"
                    disabled={comparable.length < 2}
                    title={comparable.length < 2 ? t("mediaCompareHint") : undefined}
                    onClick={() => setComparing(true)}
                  >
                    <Columns2 size={13} /> {t("mediaCompare")}
                  </Button>
                  <Button
                    variant="outline"
                    size="default"
                    disabled={selectedIds.size === 0}
                    onClick={() => setBatchTagging(true)}
                  >
                    <Tag size={13} /> {t("addTags")}
                  </Button>
                  <Button
                    variant="outline"
                    size="default"
                    className="hover:border-destructive/50 hover:text-destructive"
                    disabled={selectedIds.size === 0}
                    onClick={() => setBatchDeleting(true)}
                  >
                    <Trash2 size={13} /> {t("delete")}
                  </Button>
                  <Button variant="ghost" size="default" onClick={exitSelectMode}>
                    <X size={13} /> {t("cancel")}
                  </Button>

          </div>}
        </div>
      )}
      <UrlImportDialog
        open={urlImportOpen}
        onOpenChange={setUrlImportOpen}
        workspace={workspace}
        // 下载跑在后台任务里,完成时素材库要自己刷新 —— 不刷的话新素材要切走再切回来才看得见
        // (配音那条路正是这么被报上来的)。
        onQueued={() => void qc.invalidateQueries({ queryKey: ["assets"] })}
      />

      {assets.isSuccess && (assets.data ?? []).length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={22} />}
          title={t("mediaEmptyTitle")}
          body={t("mediaEmptyBody")}

        />
      ) : visible.length === 0 ? <EmptyState icon={<FolderOpen />} title={t("studioNoMatches")} body={t("studioNoMatchesHint")} /> : (
        <div className={cn("py-6", display === "grid" ? "grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-7" : "grid divide-y divide-divider")}>
          {visible.map((asset) => (
            <ContextMenu key={asset.id} onOpenChange={open => { if (open) setActionMenuId(null); }}>
              <ContextMenuTrigger asChild>
                <div
                  className="group relative cursor-pointer"
                  onClick={() => {
                    // 图片也先进详情卡(看得到尺寸/来源/标签等),要看大图再从卡里点开。
                    if (selectMode) toggleSelected(asset.id);
                    else setPreviewing(asset);
                  }}
                >
                  <button type="button" className="absolute inset-0 z-[1] rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={asset.name} />
                  <AssetTile asset={asset} list={display === "list"} selected={selectMode && selectedIds.has(asset.id)} />
                  {selectMode && <SelectionCheck selected={selectedIds.has(asset.id)} />}
                  {!selectMode && <div className="absolute right-2 top-2 z-10" onClick={e => e.stopPropagation()}>
                    <Popover open={actionMenuId === asset.id} onOpenChange={open => setActionMenuId(current => open ? asset.id : current === asset.id ? null : current)}><PopoverTrigger asChild><Button variant="secondary" size="icon-xs" aria-label={`${t("studioActions")}: ${asset.name}`}><MoreHorizontal /></Button></PopoverTrigger>
                    <PopoverContent className={cn(ACTION_MENU, "w-48")} align="end" onCloseAutoFocus={event => { if (actionMenuId && actionMenuId !== asset.id) event.preventDefault(); }}>
                      <PopoverClose asChild><Button variant="ghost" className="justify-start" onClick={() => saveAssetToDisk(asset)}><Download />{t("assetSaveLocal")}</Button></PopoverClose>
                      <PopoverClose asChild><Button variant="ghost" className="justify-start" onClick={() => setRenaming(asset)}><Pencil />{t("rename")}</Button></PopoverClose>
                      <PopoverClose asChild><Button variant="ghost" className="justify-start" onClick={() => setEditingTags(asset)}><Tag />{t("editTags")}</Button></PopoverClose>
                      {asset.kind === "video" && <PopoverClose asChild><Button variant="ghost" className="justify-start" loading={convertGif.isPending} onClick={() => convertGif.mutate(asset.id)}><ImagePlus />{t("assetConvertGif")}</Button></PopoverClose>}
                      <PopoverClose asChild><Button variant="ghost" className="justify-start text-destructive" onClick={() => setDeleting(asset)}><Trash2 />{t("delete")}</Button></PopoverClose>
                    </PopoverContent></Popover>
                  </div>}
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => saveAssetToDisk(asset)}>
                  <Download /> {t("assetSaveLocal")}
                </ContextMenuItem>
                <ContextMenuItem onSelect={() => setRenaming(asset)}>
                  <Pencil /> {t("rename")}
                </ContextMenuItem>
                <ContextMenuItem onSelect={() => setEditingTags(asset)}>
                  <Tag /> {t("editTags")}
                </ContextMenuItem>
                {asset.kind === "video" && (
                  <ContextMenuItem disabled={convertGif.isPending} onSelect={() => convertGif.mutate(asset.id)}>
                    {convertGif.isPending ? <Loader2 className="animate-spin" /> : <ImagePlus />} {t("assetConvertGif")}
                  </ContextMenuItem>
                )}
                <ContextMenuSeparator />
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(asset)}>
                  <Trash2 /> {t("delete")}
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenu>
          ))}
        </div>
      )}

      <AssetPreviewModal asset={previewing} onClose={() => setPreviewing(null)} />
      <RenameDialog
        open={renaming !== null}
        title={t("renameAsset")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <TagsDialog
        open={editingTags !== null}
        title={t("editTags")}
        initialTags={editingTags ? assetTags(editingTags) : []}
        onCancel={() => setEditingTags(null)}
        onSubmit={(tags) => editingTags && saveTags.mutate({ id: editingTags.id, tags })}
      />
      <TagsDialog
        open={batchTagging}
        title={t("addTags")}
        body={t("addTagsBody")}
        initialTags={[]}
        onCancel={() => setBatchTagging(false)}
        onSubmit={(tags) => tags.length > 0 && batchAddTags.mutate(tags)}
      />
      <ConfirmDialog
        open={deleting !== null || (deleteError !== null && !batchDeleting)}
        title={t("deleteConfirmTitle")}
        body={deleteError ?? t("deleteAssetBody")}
        onCancel={() => {
          setDeleting(null);
          setDeleteError(null);
        }}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
          else setDeleteError(null);
        }}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("deleteAssetsBody").replace("{n}", String(selectedIds.size))}
        onCancel={() => setBatchDeleting(false)}
        onConfirm={() => batchRemove.mutate()}
      />
      {comparing && comparable.length >= 2 && (
        <AssetCompareView assets={comparable} onClose={() => setComparing(false)} />
      )}
      </div>
    </div>
  );
}

function AssetTile({ asset, selected = false, list = false }: { asset: Asset; selected?: boolean; list?: boolean }) {
  const t = useI18n();
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const duration = asset.media_info.duration as number | undefined;
  const width = asset.media_info.width as number | undefined;
  const fps = asset.media_info.fps as number | undefined;
  const hasThumb = asset.kind !== "audio" && !thumbFailed;
  return (
    <article
      className={cn(
        "cursor-pointer rounded-lg transition-colors",
        list ? "flex items-center gap-5 py-4 pr-12 hover:bg-secondary/40" : "grid gap-3",
        selected && "border-primary shadow-[0_0_0_1px_var(--primary)]",
      )}
    >
      <div className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-panel-inset text-muted-foreground", list ? "h-20 w-32" : "aspect-video")}>
        {hasThumb ? (
          <img
            src={assetThumbnailUrl(asset.id)}
            alt=""
            loading="lazy"
            className={cn("absolute inset-0 h-full w-full", asset.kind === "image" ? "object-contain" : "object-cover")}
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span>{kindIcon(asset.kind)}</span>
        )}
        {/* 时长角标只对有时基的素材(视频/音频)有意义;图片 duration 恒为 0,别显示 00:00。 */}
        {asset.kind !== "image" && duration != null && (
          <span className="absolute bottom-1.5 right-1.5 rounded-sm bg-[rgba(10,12,15,0.75)] px-[5px] py-px font-mono text-ui-xs tabular-nums text-[#e8eaed]">
            {formatSeconds(duration)}
          </span>
        )}
        {/* 标签叠在缩略图左下角(而非信息区),这样有无标签的卡片信息区一样高、栅格不错位。 */}
        {assetTags(asset).length > 0 && (
          <div className="absolute bottom-1.5 left-1.5 flex max-w-[70%] flex-wrap gap-1">
            {assetTags(asset)
              .slice(0, 2)
              .map((tag) => (
                <span
                  className="max-w-full truncate rounded-sm bg-[rgba(10,12,15,0.72)] px-[5px] py-px text-ui-2xs text-[#e8eaed]"
                  key={tag}
                >
                  {tag}
                </span>
              ))}
            {assetTags(asset).length > 2 && (
              <span className="rounded-sm bg-[rgba(10,12,15,0.72)] px-[5px] py-px text-ui-2xs text-[#e8eaed]">
                +{assetTags(asset).length - 2}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="grid min-w-0 flex-1 gap-1.5 px-0.5">
        <strong className="truncate text-ui-md font-semibold" title={asset.name}>
          {asset.name}
        </strong>
        <div className="flex items-center gap-1.5">
          <span className="text-ui-xs text-muted-foreground">{t(asset.kind === "image" ? "kindImage" : asset.kind === "audio" ? "kindAudio" : "kindVideo")}</span>
          <small className="text-ui-xs text-muted-foreground">{asset.source === "generated" ? t("mediaSourceGenerated") : asset.source === "exported" ? t("mediaSourceExported") : t("mediaSourceImported")}</small>
        </div>
        <span className="truncate font-mono text-ui-xs tabular-nums text-muted-foreground">
          {width ? `${width}×${asset.media_info.height}` : "—"}
          {asset.kind === "video" && fps ? ` · ${Math.round(Number(fps))}fps` : ""}
          {asset.created_at ? ` · ${formatShortDate(asset.created_at)}` : ""}
        </span>
      </div>
    </article>
  );
}

function kindIcon(kind: string) {
  if (kind === "audio") return <FileAudio size={22} />;
  if (kind === "image") return <FileImage size={22} />;
  return <FileVideo size={22} />;
}

/** 后端时间是 UTC 无时区标记的 ISO 串;补 Z 再按本地时区取短日期。 */
export function formatShortDate(iso: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function formatSeconds(total: number): string {
  const sign = total < 0 ? "-" : "";
  const abs = Math.abs(total);
  const minutes = Math.floor(abs / 60);
  const seconds = Math.floor(abs % 60);
  const tenths = Math.floor((abs * 10) % 10);
  return `${sign}${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}
