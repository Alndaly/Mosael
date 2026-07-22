import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { formatTimecode } from "@/domain/timeline/geometry";

export function AssetPreviewModal({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const t = useI18n();
  const media = asset?.media_info ?? {};
  return (
    <Dialog open={asset !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-[min(960px,calc(100vw-32px))] max-w-[calc(100vw-32px)] p-4">
        {asset && (
          <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
            <div className="grid min-h-[220px] place-items-center overflow-hidden rounded-md bg-black md:min-h-[320px]">
              {asset.kind === "video" && (
                <video className="max-h-[60vh] max-w-full" src={assetFileUrl(asset.id)} controls autoPlay playsInline />
              )}
              {asset.kind === "image" && <img className="max-h-[60vh] max-w-full" src={assetFileUrl(asset.id)} alt={asset.name} />}
              {asset.kind === "audio" && <audio className="w-[90%]" src={assetFileUrl(asset.id)} controls autoPlay />}
            </div>
            <dl className="grid content-start gap-1.5 text-xs">
              <DialogTitle className="leading-snug break-all">{asset.name}</DialogTitle>
              <div>
                <dt className="text-[11px] text-muted-foreground">{t("format")}</dt>
                <dd className="mb-1.5 font-mono tabular-nums">
                  {asset.kind}
                  {media.width ? ` · ${media.width}×${media.height}` : ""}
                  {media.fps ? ` · ${Math.round(Number(media.fps))}fps` : ""}
                </dd>
              </div>
              {media.duration != null && (
                <div>
                  <dt className="text-[11px] text-muted-foreground">{t("duration")}</dt>
                  <dd className="mb-1.5 font-mono tabular-nums">{formatTimecode(Number(media.duration))}</dd>
                </div>
              )}
              <div>
                <dt className="text-[11px] text-muted-foreground">{t("mediaSourceImported")}/{t("mediaSourceGenerated")}</dt>
                <dd className="mb-1.5">
                  {asset.source === "generated" ? t("mediaSourceGenerated") : asset.source === "exported" ? "导出" : t("mediaSourceImported")}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted-foreground">ID</dt>
                <dd className="mb-1.5 break-all font-mono tabular-nums">{asset.id}</dd>
              </div>
            </dl>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
