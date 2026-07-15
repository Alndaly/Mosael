import * as DialogPrimitive from "@radix-ui/react-dialog";

import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/domain/timeline/geometry";

export function AssetPreviewModal({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const t = useI18n();
  const media = asset?.media_info ?? {};
  return (
    <DialogPrimitive.Root open={asset !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 animate-in fade-in-0" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-popover p-4 shadow-[var(--shadow-raised)] animate-in fade-in-0 zoom-in-95 outline-none">
          {asset && (
            <div className="preview-modal">
              <div className="preview-stage">
                {asset.kind === "video" && (
                  <video src={assetFileUrl(asset.id)} controls autoPlay playsInline />
                )}
                {asset.kind === "image" && <img src={assetFileUrl(asset.id)} alt={asset.name} />}
                {asset.kind === "audio" && <audio src={assetFileUrl(asset.id)} controls autoPlay />}
              </div>
              <dl className="preview-meta">
                <DialogPrimitive.Title className="text-[14px] font-semibold leading-snug break-all">
                  {asset.name}
                </DialogPrimitive.Title>
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
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
