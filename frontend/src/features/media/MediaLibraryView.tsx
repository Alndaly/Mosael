import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDot, FileAudio, FileImage, FileVideo, FolderOpen, ImagePlus, ListChecks, Pencil, Tag, Tags, Trash2, X } from "lucide-react";

import { api, assetFileUrl, assetThumbnailUrl, deleteAsset, importAsset, renameAsset, setAssetTags, type Asset, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { useImagePreview } from "@/components/app/image-preview";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { Recorder } from "@/features/editor/Recorder";
import { AssetPreviewModal } from "@/features/media/AssetPreviewModal";
import { TagsDialog } from "@/features/media/TagsDialog";

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
  const { openImagePreview } = useImagePreview();
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [previewing, setPreviewing] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [editingTags, setEditingTags] = React.useState<Asset | null>(null);
  const [kindFilter, setKindFilter] = React.useState<KindFilter>("all");
  const [tagFilter, setTagFilter] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");
  const [sortKey, setSortKey] = React.useState<SortKey>("created");
  const [selectMode, setSelectMode] = React.useState(false);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [batchTagging, setBatchTagging] = React.useState(false);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const [recorderOpen, setRecorderOpen] = React.useState(false);

  const assets = useQuery({
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["assets"] });

  // Cmd+K 面板选中素材后跳转到本页并直接打开预览。
  React.useEffect(() => {
    const onOpenAsset = (event: Event) => {
      const assetId = (event as CustomEvent<string>).detail;
      const asset = (assets.data ?? []).find((item) => item.id === assetId);
      if (!asset) return;
      if (asset.kind === "image") {
        openImagePreview({ src: assetFileUrl(asset.id), title: asset.name });
      } else {
        setPreviewing(asset);
      }
    };
    window.addEventListener("mibu:open-asset", onOpenAsset);
    return () => window.removeEventListener("mibu:open-asset", onOpenAsset);
  }, [assets.data, openImagePreview]);

  const uploadAsset = useMutation({
    // 工作区级导入:不挂 project_id,该工作区下所有项目都能用。
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, file }),
    onSuccess: refresh,
  });
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
      setSelectedIds(new Set());
      if (failures.length > 0) setDeleteError(failures.join("\n"));
      void refresh();
    },
  });

  const allTags = React.useMemo(() => {
    const set = new Set<string>();
    for (const asset of assets.data ?? []) for (const tag of assetTags(asset)) set.add(tag);
    return [...set].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [assets.data]);

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

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  const kindLabel: Record<KindFilter, string> = {
    all: t("kindAll"),
    video: t("kindVideo"),
    audio: t("kindAudio"),
    image: t("kindImage"),
  };

  return (
    <div className="feature-view">
      <div className="feature-toolbar media-toolbar">
        <div className="media-toolbar-left">
          <Button asChild size="sm">
            <label>
              <input
                type="file"
                accept="video/*,audio/*,image/*"
                className="hidden-input"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) uploadAsset.mutate(file);
                  event.currentTarget.value = "";
                }}
              />
              <ImagePlus size={13} /> {t("import")}
            </label>
          </Button>
          <Button variant="outline" size="sm" onClick={() => setRecorderOpen(true)}>
            <CircleDot size={13} /> {t("record")}
          </Button>
          <div className="seg" role="group" aria-label={t("mediaKindGroup")}>
            {KIND_FILTERS.map((kind) => (
              <button
                key={kind}
                type="button"
                className={kindFilter === kind ? "seg-btn active" : "seg-btn"}
                onClick={() => setKindFilter(kind)}
              >
                {kindLabel[kind]}
              </button>
            ))}
          </div>
          <Input
            className="toolbar-search"
            value={search}
            placeholder={t("searchAssets")}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
            <SelectTrigger aria-label={t("sortNewest")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="created">{t("sortNewest")}</SelectItem>
              <SelectItem value="updated">{t("sortUpdated")}</SelectItem>
              <SelectItem value="name">{t("sortName")}</SelectItem>
              <SelectItem value="duration">{t("sortDuration")}</SelectItem>
            </SelectContent>
          </Select>
          {allTags.length > 0 && (
            <div className="tag-filter" role="group" aria-label={t("filterByTag")}>
              <Tags size={13} />
              {allTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  className={tagFilter === tag ? "tag-chip active" : "tag-chip"}
                  onClick={() => setTagFilter((current) => (current === tag ? null : tag))}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="media-toolbar-right">
          {selectMode ? (
            <>
              <span className="media-selected-count">
                {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
              </span>
              <Button variant="outline" size="sm" onClick={() => setSelectedIds(new Set(visible.map((a) => a.id)))}>
                <ListChecks size={13} /> {t("mediaSelectAll")}
              </Button>
              <Button variant="outline" size="sm" disabled={selectedIds.size === 0} onClick={() => setBatchTagging(true)}>
                <Tag size={13} /> {t("addTags")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="danger-outline"
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={13} /> {t("delete")}
              </Button>
              <Button variant="ghost" size="sm" onClick={exitSelectMode}>
                <X size={13} /> {t("cancel")}
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
              <Check size={13} /> {t("mediaSelectMode")}
            </Button>
          )}
        </div>
      </div>
      <Recorder open={recorderOpen} onOpenChange={setRecorderOpen} onRecorded={(file) => uploadAsset.mutate(file)} />

      {(assets.data ?? []).length === 0 ? (
        <EmptyState icon={<FolderOpen size={22} />} title={t("mediaEmptyTitle")} body={t("mediaEmptyBody")} />
      ) : (
        <div className="asset-grid">
          {visible.map((asset) => (
            <ContextMenu key={asset.id}>
              <ContextMenuTrigger asChild>
                <div
                  className={selectMode && selectedIds.has(asset.id) ? "asset-cell selected" : "asset-cell"}
                  onClick={() => {
                    if (selectMode) {
                      toggleSelected(asset.id);
                    } else if (asset.kind === "image") {
                      openImagePreview({ src: assetFileUrl(asset.id), title: asset.name });
                    } else {
                      setPreviewing(asset);
                    }
                  }}
                >
                  <AssetTile asset={asset} />
                  {selectMode && (
                    <span className={selectedIds.has(asset.id) ? "asset-check on" : "asset-check"}>
                      <Check size={12} />
                    </span>
                  )}
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
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
    </div>
  );
}

function AssetTile({ asset }: { asset: Asset }) {
  const t = useI18n();
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const duration = asset.media_info.duration as number | undefined;
  const width = asset.media_info.width as number | undefined;
  const fps = asset.media_info.fps as number | undefined;
  const hasThumb = asset.kind !== "audio" && !thumbFailed;
  return (
    <article className="asset-tile">
      <div className="asset-thumb" data-kind={asset.kind}>
        {hasThumb ? (
          <img
            src={assetThumbnailUrl(asset.id)}
            alt=""
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span className="asset-thumb-fallback">{kindIcon(asset.kind)}</span>
        )}
        {/* 时长角标只对有时基的素材(视频/音频)有意义;图片 duration 恒为 0,别显示 00:00。 */}
        {asset.kind !== "image" && duration != null && (
          <span className="asset-duration timecode">{formatSeconds(duration)}</span>
        )}
      </div>
      <div className="asset-caption">
        <strong title={asset.name}>{asset.name}</strong>
        <div className="asset-meta">
          <Badge variant="secondary">{asset.kind}</Badge>
          <small>{asset.source === "generated" ? t("mediaSourceGenerated") : asset.source === "exported" ? t("mediaSourceExported") : t("mediaSourceImported")}</small>
        </div>
        {assetTags(asset).length > 0 && (
          <div className="asset-tags">
            {assetTags(asset)
              .slice(0, 3)
              .map((tag) => (
                <span className="tag-chip readonly" key={tag}>
                  {tag}
                </span>
              ))}
            {assetTags(asset).length > 3 && (
              <span className="tag-chip readonly">+{assetTags(asset).length - 3}</span>
            )}
          </div>
        )}
        <span className="asset-specs timecode">
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
