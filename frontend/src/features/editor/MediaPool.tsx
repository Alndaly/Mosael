import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleDot, Download, FileAudio, FileImage, FileVideo, ImagePlus, ListPlus, Pencil, Plus, Search, Tag, Trash2 } from "lucide-react";

import { assetPreviewUrl, assetThumbnailUrl, deleteAsset, renameAsset, setAssetTags, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { TagsDialog } from "@/features/media/TagsDialog";
import { useImagePreview } from "@/components/app/image-preview";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { formatTimecode } from "@/domain/timeline/geometry";
import { useEditorStore } from "@/stores/editorStore";
import { cn } from "@/lib/utils";
import { saveAssetToDisk } from "@/lib/download";
import { useDraggable } from "@dnd-kit/core";

const KIND_FILTERS = ["all", "video", "audio", "image"] as const;
type KindFilter = (typeof KIND_FILTERS)[number];

export function MediaPool({
  assets,
  uploading,
  onImportFile,
  onRecord,
  onAddToTimeline,
  tabs,
}: {
  assets: Asset[];
  uploading: boolean;
  onImportFile: (file: File) => void;
  onRecord: () => void;
  onAddToTimeline: (asset: Asset) => void;
  tabs?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [editingTags, setEditingTags] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [kindFilter, setKindFilter] = React.useState<KindFilter>("all");
  const [search, setSearch] = React.useState("");
  const [selectedTags, setSelectedTags] = React.useState<string[]>([]);
  // 当前(按类型过滤后的)素材里出现过的标签,去重排序 —— 只列真实存在的标签,避免筛出空结果。
  const availableTags = React.useMemo(() => {
    const set = new Set<string>();
    for (const asset of assets) {
      if (kindFilter !== "all" && asset.kind !== kindFilter) continue;
      for (const tag of asset.tags ?? []) if (tag) set.add(tag);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "zh"));
  }, [assets, kindFilter]);
  // 选中的标签若因切换类型而不再存在,自动剔除,别留下永远筛不出东西的"幽灵标签"。
  React.useEffect(() => {
    setSelectedTags((current) => current.filter((tag) => availableTags.includes(tag)));
  }, [availableTags]);
  const toggleTag = (tag: string) =>
    setSelectedTags((current) => (current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]));
  const visibleAssets = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    return assets.filter((asset) => {
      const tags = asset.tags ?? [];
      // 多选标签取交集(每个选中标签都得有),这样点得越多筛得越窄。
      const matchesTags = selectedTags.length === 0 || selectedTags.every((tag) => tags.includes(tag));
      return (
        matchesTags &&
        (kindFilter === "all" || asset.kind === kindFilter) &&
        (query === "" ||
          asset.name.toLowerCase().includes(query) ||
          tags.some((tag) => tag.toLowerCase().includes(query)) ||
          asset.kind.toLowerCase().includes(query))
      );
    });
  }, [assets, kindFilter, search, selectedTags]);
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
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const saveTags = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => setAssetTags(id, tags),
    onSuccess: () => {
      setEditingTags(null);
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => {
      setDeleting(null);
      setDeleteError(null);
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (error) => setDeleteError(String((error as Error).message)),
  });
  return (
    // 三行:头 / 筛选条 / 列表(列表占满余高并自滚)。
    <section className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_minmax(0,1fr)] editor-pane overflow-hidden bg-workspace-panel">
      <div className="editor-pane-header flex items-center justify-between gap-2 px-4">
        <div className="flex min-w-0 items-center gap-2">{tabs ?? <h2>{t("media")}</h2>}<span className="text-ui-xs tabular-nums text-muted-foreground">{assets.length}</span></div>
        <div className="ml-auto flex shrink-0 gap-1">
          {/* Keep import and recording reachable in every panel width. */}
          <Button asChild variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-foreground" disabled={uploading} title={t("import")} aria-label={t("import")}>
            <label>
              <input
                type="file"
                accept="video/*,audio/*,image/*"
                className="hidden"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) onImportFile(file);
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
      <div className="grid gap-3 px-3 pb-3">
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input className="h-8 pl-8 text-ui-xs" value={search} placeholder={t("searchAssets")} onChange={(event) => setSearch(event.target.value)} aria-label={t("searchAssets")} />
          </div>
          {availableTags.length > 0 && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label={t("mediaTagFilter")} title={t("mediaTagFilter")} className={cn("relative shrink-0", selectedTags.length > 0 && "bg-accent text-accent-foreground")}>
                  <Tag size={15} />
                  {selectedTags.length > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-primary px-1 text-ui-2xs text-primary-foreground">{selectedTags.length}</span>}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-60 p-3">
                <div className="flex max-h-60 flex-wrap gap-1.5 overflow-auto" role="group" aria-label={t("mediaTagFilter")}>
                  {availableTags.map((tag) => (
                    <button key={tag} type="button" aria-pressed={selectedTags.includes(tag)} onClick={() => toggleTag(tag)} className={cn("rounded-md px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground", selectedTags.includes(tag) && "bg-accent text-accent-foreground")}>
                      {tag}
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          )}
        </div>
        <div className="grid grid-cols-4 gap-1" role="group" aria-label={t("mediaKindGroup")}>
          {KIND_FILTERS.map((kind) => (
            <button key={kind} type="button" aria-pressed={kindFilter === kind} className={cn("flex h-8 min-w-0 cursor-pointer items-center justify-center rounded-md text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground", kindFilter === kind && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")} onClick={() => setKindFilter(kind)}>
              {kindLabel[kind]}
            </button>
          ))}
        </div>
      </div>
      <div className="grid content-start gap-1 overflow-auto px-2 pb-2 [&:has(>.empty-inline:only-child)]:content-stretch [&:has(>.empty-inline:only-child)]:h-full">
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
        <small className="timecode">{duration != null ? formatTimecode(duration) : t(asset.kind === "image" ? "kindImage" : asset.kind === "audio" ? "kindAudio" : "kindVideo")}</small>
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
