import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleDot, Download, FileAudio, FileImage, FileVideo, ImagePlus, ListPlus, Pencil, Plus, Search, Tag, Trash2 } from "lucide-react";

import { assetPreviewUrl, assetThumbnailUrl, deleteAsset, renameAsset, setAssetTags, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { TagsDialog } from "@/features/media/TagsDialog";
import { ActiveTagChips, MediaTagFilter } from "@/features/media/MediaTagFilter";
import { TagChips } from "@/features/media/TagChips";
import { TAG_MATCHES, assetTags, matchesTags, tagCounts, type TagMatch } from "@/features/media/assetTags";
import { useImagePreview } from "@/components/app/image-preview";
import { Input } from "@/components/ui/input";
import { formatTimecode } from "@/domain/timeline/geometry";
import { cn } from "@/lib/utils";
import { saveAssetToDisk } from "@/lib/download";
import { usePersistentSet, usePersistentTab } from "@/lib/usePersistentTab";
import { useDraggable } from "@dnd-kit/core";

const KIND_FILTERS = ["all", "video", "audio", "image"] as const;
type KindFilter = (typeof KIND_FILTERS)[number];

export function MediaPool({
  assets,
  uploading,
  onImportFiles,
  onRecord,
  onAddToTimeline,
}: {
  assets: Asset[];
  uploading: boolean;
  onImportFiles: (files: File[]) => void;
  onRecord: () => void;
  onAddToTimeline: (asset: Asset) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [editingTags, setEditingTags] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  // 类型、标签筛选和素材库一个规矩:记住,切走再回来还在。键和素材库分开 —— 这里看的是
  // 当前工程的素材,那边是整个工作区的,两处各筛各的。
  const [kindFilter, setKindFilter] = usePersistentTab<KindFilter>("editor-pool-kind", "all", KIND_FILTERS);
  const [search, setSearch] = React.useState("");
  const tagCount = React.useMemo(() => tagCounts(assets), [assets]);
  const allTags = React.useMemo(() => [...tagCount.keys()], [tagCount]);
  // 存着一个已经没有素材带着的标签时当作没勾(usePersistentSet 自己验),面板不会空得莫名其妙。
  const [tagFilter, setTagFilter] = usePersistentSet("editor-pool-tags", allTags);
  const [tagMatch, setTagMatch] = usePersistentTab<TagMatch>("editor-pool-tag-match", "all", TAG_MATCHES);
  const visibleAssets = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    return assets.filter(
      (asset) =>
        matchesTags(asset, tagFilter, tagMatch) &&
        (kindFilter === "all" || asset.kind === kindFilter) &&
        (query === "" ||
          asset.name.toLowerCase().includes(query) ||
          assetTags(asset).some((tag) => tag.toLowerCase().includes(query)) ||
          asset.kind.toLowerCase().includes(query)),
    );
  }, [assets, kindFilter, search, tagFilter, tagMatch]);
  // 头上那个数要说清楚是什么:没筛就是「N 个素材」,筛了就是「剩几个 / 一共几个」。
  const filtering = kindFilter !== "all" || tagFilter.length > 0 || search.trim() !== "";
  const countLabel = filtering
    ? t("mediaPoolCountFiltered").replace("{shown}", String(visibleAssets.length)).replace("{total}", String(assets.length))
    : t("mediaPoolCount").replace("{count}", String(assets.length));
  const kindLabel: Record<KindFilter, string> = {
    all: t("kindAll"),
    video: t("kindVideo"),
    audio: t("kindAudio"),
    image: t("kindImage"),
  };
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameAsset(id, name),
    onSuccess: () => {
      setRenaming(null);
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
    },
  });
  const saveTags = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => setAssetTags(id, tags),
    onSuccess: () => {
      setEditingTags(null);
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => {
      setDeleting(null);
      setDeleteError(null);
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
    },
    onError: (error) => setDeleteError(String((error as Error).message)),
  });
  return (
    // 三行:头 / 筛选条 / 列表(列表占满余高并自滚)。头和筛选条左右都是 px-3;列表的左右留白
    // 见 .editor-pool-list(滚动条的位置两边各留一份,左右才对称)。
    <section aria-label={t("media")} className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_minmax(0,1fr)] editor-pane overflow-hidden bg-workspace-panel">
      <div className="editor-pane-header flex items-center justify-between gap-2 px-3">
        <span className="min-w-0 truncate text-ui-xs tabular-nums text-muted-foreground" data-pool-count>{countLabel}</span>
        <div className="ml-auto flex shrink-0 gap-1">
          {/* Keep import and recording reachable in every panel width. */}
          <Button asChild variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" disabled={uploading} title={t("import")} aria-label={t("import")}>
            <label>
              <input
                type="file"
                accept="video/*,audio/*,image/*"
                multiple
                className="hidden"
                onChange={(event) => {
                  const files = [...(event.currentTarget.files ?? [])];
                  if (files.length > 0) onImportFiles(files);
                  event.currentTarget.value = "";
                }}
              />
              <ImagePlus size={14} />
            </label>
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            onClick={onRecord}
            title={t("record")}
            aria-label={t("record")}
          >
            <CircleDot size={14} />
          </Button>
        </div>
      </div>
      <div className="grid gap-2 px-3 pb-3">
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input size="sm" className="pl-8 text-ui-xs" value={search} placeholder={t("searchAssets")} onChange={(event) => setSearch(event.target.value)} aria-label={t("searchAssets")} />
          </div>
          {allTags.length > 0 && <MediaTagFilter compact counts={tagCount} value={tagFilter} onChange={setTagFilter} match={tagMatch} onMatchChange={setTagMatch} />}
        </div>
        <ActiveTagChips value={tagFilter} onChange={setTagFilter} match={tagMatch} />
        {/* 四等分,字放不下就省略 —— 面板最窄 180px 时一格只有三十来像素,不能让字顶出格子。 */}
        <div className="grid grid-cols-4 gap-1" role="group" aria-label={t("mediaKindGroup")}>
          {KIND_FILTERS.map((kind) => (
            <button key={kind} type="button" aria-pressed={kindFilter === kind} title={kindLabel[kind]} className={cn("flex h-8 min-w-0 cursor-pointer items-center justify-center rounded-md px-1 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground", kindFilter === kind && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")} onClick={() => setKindFilter(kind)}>
              <span className="min-w-0 truncate">{kindLabel[kind]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="editor-pool-list grid content-start gap-1 overflow-y-auto px-1 pb-2 [&:has(>.empty-inline:only-child)]:content-stretch [&:has(>.empty-inline:only-child)]:h-full">
        {visibleAssets.map((asset) => (
          <ContextMenu key={asset.id}>
            <ContextMenuTrigger asChild>
              <div>
                <PoolItem asset={asset} onAdd={() => onAddToTimeline(asset)} />
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent>
              <ContextMenuItem onSelect={() => onAddToTimeline(asset)}>
                <ListPlus /> {t("addToTimeline")}
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => saveAssetToDisk(asset)}>
                <Download /> {t("assetSaveLocal")}
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => setRenaming(asset)}>
                <Pencil /> {t("rename")}
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => setEditingTags(asset)}>
                <Tag /> {t("editTags")}
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(asset)}>
                <Trash2 /> {t("delete")}
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        ))}
        {assets.length === 0 && <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-ui-sm leading-[1.6] text-muted-foreground">{t("mediaEmptyBody")}</div>}
        {assets.length > 0 && visibleAssets.length === 0 && <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-ui-sm leading-[1.6] text-muted-foreground">{t("mediaNoMatchingAssets")}</div>}
      </div>

      <RenameDialog
        open={renaming !== null}
        title={t("renameAsset")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        pending={rename.isPending}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <TagsDialog
        open={editingTags !== null}
        title={t("editTags")}
        initialTags={editingTags?.tags ?? []}
        onCancel={() => setEditingTags(null)}
        onSubmit={(tags) => editingTags && saveTags.mutate({ id: editingTags.id, tags })}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={deleteError ?? t("deleteAssetBody")}
        onCancel={() => {
          setDeleting(null);
          setDeleteError(null);
        }}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </section>
  );
}

function PoolItem({ asset, onAdd }: { asset: Asset; onAdd: () => void }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  // dnd-kit(指针驱动):原生 HTML5 拖拽在 Electron + Radix 包裹下不可靠,这里全面换掉。
  const { setNodeRef, listeners, attributes } = useDraggable({ id: `asset-${asset.id}`, data: { asset } });
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : null;
  const hasThumb = Boolean(asset.media_info.has_thumbnail) && !thumbFailed;
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      data-pool-item={asset.id}
      className="group/pool relative grid cursor-grab select-none grid-cols-[80px_minmax(0,1fr)] items-center gap-3 rounded-lg px-2 py-2 transition-colors duration-150 hover:bg-control active:cursor-grabbing"
      onDoubleClick={onAdd}
      title={`${asset.name} — ${t("addToTimeline")}`}
    >
      {/* 缩略图必须 absolute 铺满(而不是 h-full/w-full):容器是 grid + place-items-center,
          行高按内容 auto 算且不拉伸,百分比高度因此没有参照、退化成图片固有高度 —— 竖图会
          撑成 64×96 溢出 36px 的框,被 overflow-hidden 从下方切掉,只剩顶部(实测如此)。
          absolute inset-0 让图精确等于框,object-cover 才真的从中心裁切。 */}
      <div
        className={cn("relative grid aspect-video place-items-center overflow-hidden rounded-sm bg-panel-inset text-muted-foreground [&_img]:absolute [&_img]:inset-0 [&_img]:h-full [&_img]:w-full [&_img]:object-cover", asset.kind === "image" && "cursor-zoom-in")}
        onClick={(event) => {
          if (asset.kind !== "image") return;
          event.stopPropagation();
          openImagePreview({ src: assetPreviewUrl(asset.id), title: asset.name });
        }}
      >
        {hasThumb ? <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" onError={() => setThumbFailed(true)} /> : kindIcon(asset.kind)}
      </div>
      <div className="min-w-0 [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-ui-sm [&_strong]:font-medium">
        <strong>{asset.name}</strong>
        {/* 标签和时长同一行,有没有标签行高都一样;挤不下的标签收成「+N」,面板拖到最窄时
            标签先被截掉,不把行撑出面板。 */}
        <span className="flex min-w-0 items-center gap-1.5">
          <small className="timecode shrink-0">{duration != null ? formatTimecode(duration) : t(asset.kind === "image" ? "kindImage" : asset.kind === "audio" ? "kindAudio" : "kindVideo")}</small>
          <TagChips tags={assetTags(asset)} tone="surface" className="overflow-hidden" />
        </span>
      </div>
      <button
        type="button"
        className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 cursor-pointer place-items-center rounded-md bg-popover text-muted-foreground opacity-0 transition-[opacity,color,background-color] duration-150 hover:text-primary group-hover/pool:opacity-100 group-focus-within/pool:opacity-100"
        title={t("addToTimeline")}
        aria-label={t("addToTimeline")}
        onClick={(event) => {
          event.stopPropagation();
          onAdd();
        }}
      >
        <Plus size={13} />
      </button>
    </div>
  );
}

function kindIcon(kind: string) {
  if (kind === "audio") return <FileAudio size={16} />;
  if (kind === "image") return <FileImage size={16} />;
  return <FileVideo size={16} />;
}
