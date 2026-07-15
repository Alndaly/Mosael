import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileAudio, FileImage, FileVideo, ImagePlus, ListPlus, Pencil, Trash2 } from "lucide-react";

import { assetThumbnailUrl, deleteAsset, renameAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { formatTimecode } from "@/domain/timeline/geometry";

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
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameAsset(id, name),
    onSuccess: () => {
      setRenaming(null);
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
    <section className="panel media-panel">
      <div className="panel-head">
        {tabs ?? <h2>{t("media")}</h2>}
        <Button asChild variant="outline" size="sm" disabled={uploading}>
          <label>
            <input
              type="file"
              accept="video/*,audio/*,image/*"
              className="hidden-input"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) onImportFile(file);
                event.currentTarget.value = "";
              }}
            />
            <ImagePlus size={14} /> {t("import")}
          </label>
        </Button>
      </div>
      <div className="pool-list">
        {assets.map((asset) => (
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
              <ContextMenuItem onSelect={() => setRenaming(asset)}>
                <Pencil /> {t("rename")}
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem destructive onSelect={() => setDeleting(asset)}>
                <Trash2 /> {t("delete")}
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        ))}
        {assets.length === 0 && <div className="empty-inline">{t("mediaEmptyBody")}</div>}
      </div>

      <RenameDialog
        open={renaming !== null}
        title={t("renameAsset")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
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
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : null;
  const hasThumb = Boolean(asset.media_info.has_thumbnail) && !thumbFailed;
  return (
    <div
      className="pool-item"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData("application/x-mibu-asset", asset.id);
        event.dataTransfer.effectAllowed = "copy";
      }}
      onDoubleClick={onAdd}
      title={`${asset.name} — ${t("addToTimeline")}`}
    >
      <div className="pool-thumb">
        {hasThumb ? <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" onError={() => setThumbFailed(true)} /> : kindIcon(asset.kind)}
      </div>
      <div className="pool-meta">
        <strong>{asset.name}</strong>
        <small className="timecode">{duration != null ? formatTimecode(duration) : asset.kind}</small>
      </div>
    </div>
  );
}

function kindIcon(kind: string) {
  if (kind === "audio") return <FileAudio size={16} />;
  if (kind === "image") return <FileImage size={16} />;
  return <FileVideo size={16} />;
}
