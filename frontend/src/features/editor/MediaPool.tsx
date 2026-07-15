import React from "react";
import { FileAudio, FileImage, FileVideo, ImagePlus } from "lucide-react";

import { assetThumbnailUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
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
          <PoolItem key={asset.id} asset={asset} onAdd={() => onAddToTimeline(asset)} />
        ))}
        {assets.length === 0 && <div className="empty-inline">{t("mediaEmptyBody")}</div>}
      </div>
    </section>
  );
}

function PoolItem({ asset, onAdd }: { asset: Asset; onAdd: () => void }) {
  const t = useI18n();
  const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : null;
  const hasThumb = Boolean(asset.media_info.has_thumbnail);
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
        {hasThumb ? <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" /> : kindIcon(asset.kind)}
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
