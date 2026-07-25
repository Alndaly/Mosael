import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleDot, Download, FileAudio, FileImage, FileVideo, ImagePlus, ListPlus, Pencil, Plus, Search, Tag, Trash2 } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, deleteAsset, renameAsset, setAssetTags, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { TagsDialog } from "@/features/media/TagsDialog";
import { useImagePreview } from "@/components/app/image-preview";
import { Input } from "@/components/ui/input";
import { Recorder } from "@/features/editor/Recorder";
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
  onAddToTimeline,
  tabs,
}: {
  assets: Asset[];
  uploading: boolean;
  onImportFile: (file: File) => void;
  onAddToTimeline: (asset: Asset) => void;
  tabs?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [recorderOpen, setRecorderOpen] = React.useState(false);
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
    <section className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)]">
      <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
        {tabs ?? <h2>{t("media")}</h2>}
        <div className="flex shrink-0 gap-1">
          {/* Icon-only so the four CJK tabs + these two actions fit the narrow media panel. */}
          <Button asChild variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" disabled={uploading} title={t("import")} aria-label={t("import")}>
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
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={() => setRecorderOpen(true)}
            title={t("record")}
            aria-label={t("record")}
          >
            <CircleDot size={14} />
          </Button>
        </div>
      </div>
      <Recorder open={recorderOpen} onOpenChange={setRecorderOpen} onRecorded={onImportFile} />
      <div className="grid gap-1.5 border-b border-border p-1.5">
        <div className="relative grid [&_svg]:pointer-events-none [&_svg]:absolute [&_svg]:left-2 [&_svg]:top-1/2 [&_svg]:z-[1] [&_svg]:-translate-y-1/2 [&_svg]:text-muted-foreground [&_input]:h-7 [&_input]:pl-7 [&_input]:text-xs">
          <Search size={13} />
          <Input
            value={search}
            placeholder={t("searchAssets")}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t("searchAssets")}
          />
        </div>
        <div className="grid h-7 w-full grid-cols-4 overflow-hidden rounded-full border border-border bg-panel [&>button]:min-w-0 [&>button]:justify-center [&>button]:px-0 [&>button+button]:border-l [&>button+button]:border-border" role="group" aria-label={t("mediaKindGroup")}>
          {KIND_FILTERS.map((kind) => (
            <button
              key={kind}
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", kindFilter === kind && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => setKindFilter(kind)}
            >
              {kindLabel[kind]}
            </button>
          ))}
        </div>
        {/* 标签筛选:只列当前类型下真实存在的标签;多选取交集,点亮的再点一下即取消。 */}
        {availableTags.length > 0 && (
          <div className="flex max-h-[62px] flex-wrap gap-1 overflow-y-auto" role="group" aria-label={t("mediaTagFilter")}>
            {availableTags.map((tag) => {
              const active = selectedTags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleTag(tag)}
                  className={cn(
                    "inline-flex max-w-full cursor-pointer items-center truncate rounded-full border border-border bg-panel px-2 py-[2px] text-[11px] text-muted-foreground transition-colors duration-100 hover:border-border-strong hover:text-foreground",
                    active &&
                      "border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary hover:text-primary",
                  )}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="grid content-start gap-1.5 overflow-auto p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch [&:has(>.empty-inline:only-child)]:h-full">
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
        {assets.length === 0 && <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-[13px] leading-[1.6] text-muted-foreground">{t("mediaEmptyBody")}</div>}
        {assets.length > 0 && visibleAssets.length === 0 && <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-[13px] leading-[1.6] text-muted-foreground">{t("mediaNoMatchingAssets")}</div>}
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
      className="group/pool relative grid cursor-grab select-none grid-cols-[64px_minmax(0,1fr)] items-center gap-[9px] rounded-md border border-border bg-panel p-1.5 transition-[background-color,border-color] duration-100 hover:border-border-strong hover:bg-muted active:cursor-grabbing"
      onDoubleClick={onAdd}
      title={`${asset.name} — ${t("addToTimeline")}`}
    >
      <div
        className={cn("grid aspect-video place-items-center overflow-hidden rounded-sm bg-panel-inset text-muted-foreground [&_img]:h-full [&_img]:w-full [&_img]:object-cover", asset.kind === "image" && "cursor-zoom-in")}
        onClick={(event) => {
          if (asset.kind !== "image") return;
          event.stopPropagation();
          openImagePreview({ src: assetFileUrl(asset.id), title: asset.name });
        }}
      >
        {hasThumb ? <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" onError={() => setThumbFailed(true)} /> : kindIcon(asset.kind)}
      </div>
      <div className="min-w-0 [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-xs [&_strong]:font-semibold">
        <strong>{asset.name}</strong>
        <small className="timecode">{duration != null ? formatTimecode(duration) : asset.kind}</small>
      </div>
      <button
        type="button"
        className="absolute right-2 top-1/2 grid h-[22px] w-[22px] -translate-y-1/2 cursor-pointer place-items-center rounded-md border border-border bg-background text-muted-foreground opacity-0 transition-[opacity,color,border-color] duration-100 hover:border-primary hover:text-primary group-hover/pool:opacity-100"
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
