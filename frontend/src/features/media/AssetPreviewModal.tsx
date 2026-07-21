import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { formatTimecode } from "@/domain/timeline/geometry";

export function AssetPreviewModal({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const t = useI18n();
  const media = asset?.media_info ?? {};
  return (
    <Dialog open={asset !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="z-50 p-4">
        {asset && (
          <div className="preview-modal">
            <div className="preview-stage">
              {asset.kind === "video" && <video src={assetFileUrl(asset.id)} controls autoPlay playsInline />}
              {asset.kind === "image" && <img src={assetFileUrl(asset.id)} alt={asset.name} />}
              {asset.kind === "audio" && <audio src={assetFileUrl(asset.id)} controls autoPlay />}
            </div>
            <dl className="preview-meta">
              <DialogTitle className="leading-snug break-all">{asset.name}</DialogTitle>
              <div>
                <dt>{t("format")}</dt>
                <dd className="timecode">
                  {asset.kind}
                  {media.width ? ` · ${media.width}×${media.height}` : ""}
                  {media.fps ? ` · ${Math.round(Number(media.fps))}fps` : ""}
                </dd>
              </div>
              {media.duration != null && (
                <div>
                  <dt>{t("duration")}</dt>
                  <dd className="timecode">{formatTimecode(Number(media.duration))}</dd>
                </div>
              )}
              <div>
                <dt>{t("mediaSourceImported")}/{t("mediaSourceGenerated")}</dt>
                <dd>{asset.source === "generated" ? t("mediaSourceGenerated") : asset.source === "exported" ? "导出" : t("mediaSourceImported")}</dd>
              </div>
              <div>
                <dt>ID</dt>
                <dd className="timecode break-all">{asset.id}</dd>
              </div>
            </dl>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
