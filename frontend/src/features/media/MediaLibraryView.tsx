import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileAudio, FileImage, FileVideo, FolderOpen, ImagePlus, Pencil, Trash2 } from "lucide-react";

import { API_BASE, api, deleteAsset, importAsset, renameAsset, type Asset, type Project, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";

export function MediaLibraryView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Asset | null>(null);
  const [deleting, setDeleting] = React.useState<Asset | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const assets = useQuery({
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
  });
  const uploadAsset = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, projectId: project?.id ?? "", file }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets"] }),
  });
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
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("mediaTitle")}</h1>
          <p>{t("mediaDescription")}</p>
        </div>
        <Button asChild>
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
            <ImagePlus size={15} /> {t("import")}
          </label>
        </Button>
      </header>

      {(assets.data ?? []).length === 0 ? (
        <EmptyState icon={<FolderOpen size={22} />} title={t("mediaEmptyTitle")} body={t("mediaEmptyBody")} />
      ) : (
        <div className="asset-grid">
          {(assets.data ?? []).map((asset) => (
            <ContextMenu key={asset.id}>
              <ContextMenuTrigger asChild>
                <div>
                  <AssetTile asset={asset} />
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
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
        </div>
      )}

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
    </div>
  );
}

function AssetTile({ asset }: { asset: Asset }) {
  const t = useI18n();
  const duration = asset.media_info.duration as number | undefined;
  const hasThumb = Boolean(asset.media_info.has_thumbnail);
  return (
    <article className="asset-tile">
      <div className="asset-thumb">
        {hasThumb ? (
          <img src={`${API_BASE}/api/assets/${asset.id}/thumbnail`} alt="" loading="lazy" />
        ) : (
          <span className="asset-thumb-fallback">{kindIcon(asset.kind)}</span>
        )}
        {duration != null && <span className="asset-duration timecode">{formatSeconds(duration)}</span>}
      </div>
      <div className="asset-caption">
        <strong title={asset.name}>{asset.name}</strong>
        <div className="asset-meta">
          <Badge variant="secondary">{asset.kind}</Badge>
          <small>{asset.source === "generated" ? t("mediaSourceGenerated") : t("mediaSourceImported")}</small>
        </div>
      </div>
    </article>
  );
}

function kindIcon(kind: string) {
  if (kind === "audio") return <FileAudio size={22} />;
  if (kind === "image") return <FileImage size={22} />;
  return <FileVideo size={22} />;
}

export function formatSeconds(total: number): string {
  const sign = total < 0 ? "-" : "";
  const abs = Math.abs(total);
  const minutes = Math.floor(abs / 60);
  const seconds = Math.floor(abs % 60);
  const tenths = Math.floor((abs * 10) % 10);
  return `${sign}${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}
