import * as React from "react";
import { Check, Copy, Maximize2 } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useImagePreview } from "@/components/app/image-preview";
import { MediaPreviewPlayer } from "@/components/app/MediaPreviewPlayer";
import { formatTimecode } from "@/domain/timeline/geometry";
import { cn } from "@/lib/utils";

/** 后端时间是无时区的 UTC ISO 串;补 Z 再按本地时区显示到分钟。 */
function formatDateTime(iso: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}`;
}

/** 最大公约数,用来把 1920×1080 化简成 16:9 之类的宽高比。 */
function aspectRatio(w: number, h: number): string {
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
  const g = gcd(w, h) || 1;
  return `${Math.round(w / g)}:${Math.round(h / g)}`;
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] items-baseline gap-3">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 text-ui-sm text-foreground [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/**
 * 素材详情预览:顶部标题和分类,下方媒体与元数据;窄窗口将元数据移到媒体下方。
 * 图片可继续点开全屏,视频和音频共用播放控件。
 */
export function AssetPreviewModal({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const t = useI18n();
  const { openImagePreview, isImagePreviewOpen } = useImagePreview();
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    setCopied(false);
  }, [asset?.id]);

  if (!asset) return <Dialog open={false} onOpenChange={(open) => !open && onClose()} />;

  const media = asset.media_info ?? {};
  const width = Number(media.width) || 0;
  const height = Number(media.height) || 0;
  const fps = Number(media.fps) || 0;
  const duration = media.duration != null ? Number(media.duration) : null;
  // Chromium does not decode HEIC/HEIF. Images must use the backend's browser-compatible
  // representation; video and audio still stream the untouched original file.
  const src = asset.kind === "image" ? assetPreviewUrl(asset.id) : assetFileUrl(asset.id);
  const kindLabel = asset.kind === "video" ? t("kindVideo") : asset.kind === "audio" ? t("kindAudio") : t("kindImage");
  const sourceLabel =
    asset.source === "generated" ? t("mediaSourceGenerated") : asset.source === "exported" ? t("mediaSourceExported") : t("mediaSourceImported");
  const tags = asset.tags ?? [];

  const copyId = () => {
    void navigator.clipboard.writeText(asset.id).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  const handleOpenChange = (open: boolean) => {
    // PhotoSlider lives in its own portal above this Dialog. Its Esc and pointer events are
    // "outside" from Radix's perspective, so both modal layers otherwise close together.
    if (!open && !isImagePreviewOpen) onClose();
  };

  return (
    <Dialog open onOpenChange={handleOpenChange}>
      <DialogContent className={cn("w-[min(1040px,calc(100vw-32px))] max-w-[calc(100vw-32px)] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0", asset.kind === "audio" ? "h-[min(480px,86dvh)] md:w-[min(880px,calc(100vw-32px))]" : "h-[min(720px,86dvh)]")}>
        <header className="grid min-w-0 gap-2 border-b border-divider px-5 py-4 pr-14">
          <DialogTitle className="min-w-0 max-h-24 overflow-y-auto whitespace-normal text-ui-lg leading-snug [overflow-wrap:anywhere]">{asset.name}</DialogTitle>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{kindLabel}</Badge>
            <Badge variant="outline">{sourceLabel}</Badge>
          </div>
        </header>
        <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(200px,1fr)_minmax(0,180px)] md:grid-cols-[minmax(0,1fr)_300px] md:grid-rows-[minmax(0,1fr)]">
          <div className="relative grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden bg-workspace-subtle">
            {(asset.kind === "video" || asset.kind === "audio") && (
              <MediaPreviewPlayer key={asset.id} kind={asset.kind} src={src} assetId={asset.id} />
            )}
            {asset.kind === "image" && (
              <button
                type="button"
                title={t("assetClickToZoom")}
                className="group/zoom relative grid h-full min-h-0 w-full min-w-0 cursor-zoom-in place-items-center border-0 bg-transparent p-4"
                onClick={() => openImagePreview({ src, title: asset.name })}
              >
                <img className="h-full min-h-0 w-full min-w-0 object-contain" src={src} alt={asset.name} />
                <span className="pointer-events-none absolute bottom-3 right-3 inline-flex items-center gap-1 rounded-md bg-black/60 px-2 py-1 text-ui-xs text-white opacity-0 transition-opacity duration-150 group-hover/zoom:opacity-100 group-focus-visible/zoom:opacity-100">
                  <Maximize2 size={12} /> {t("assetClickToZoom")}
                </span>
              </button>
            )}
          </div>
          <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-5 overflow-y-auto border-t border-divider bg-workspace-panel p-5 md:border-l md:border-t-0">
            {tags.length > 0 && (
              <div className="grid gap-1">
                <span className="text-ui-xs text-muted-foreground">{t("assetTagsLabel")}</span>
                <div className="flex flex-wrap gap-1">
                  {tags.map((tag) => (
                    <span
                      className="inline-flex max-w-full items-center break-all rounded-full bg-control px-2 py-px text-ui-xs text-muted-foreground"
                      key={tag}
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <dl className="m-0 grid min-w-0 gap-4">
              {width > 0 && height > 0 && (
                <InfoRow label={t("assetDimensions")}>
                  <span className="font-mono tabular-nums">{width}×{height}</span>
                  <span className="ml-1.5 text-muted-foreground">({aspectRatio(width, height)})</span>
                </InfoRow>
              )}
              {asset.kind !== "image" && duration != null && duration > 0 && (
                <InfoRow label={t("duration")}>
                  <span className="font-mono tabular-nums">{formatTimecode(duration)}</span>
                </InfoRow>
              )}
              {asset.kind === "video" && fps > 0 && (
                <InfoRow label={t("assetFps")}>
                  <span className="font-mono tabular-nums">{Math.round(fps)}fps</span>
                </InfoRow>
              )}
              {asset.original_filename && asset.original_filename !== asset.name && (
                <InfoRow label={t("assetOriginalName")}>{asset.original_filename}</InfoRow>
              )}
              {asset.created_at && (
                <InfoRow label={t("assetCreated")}>
                  <span className="font-mono tabular-nums">{formatDateTime(asset.created_at)}</span>
                </InfoRow>
              )}
              <InfoRow label="ID">
                <button
                  type="button"
                  onClick={copyId}
                  className="group/id inline-flex max-w-full items-center gap-1 rounded-sm text-left font-mono text-ui-xs tabular-nums text-muted-foreground transition-colors hover:text-foreground"
                  title={copied ? t("assetIdCopied") : "复制 ID"}
                >
                  <span className="truncate">{asset.id}</span>
                  {copied ? (
                    <Check size={12} className="shrink-0 text-success" />
                  ) : (
                    <Copy size={12} className={cn("shrink-0 opacity-0 transition-opacity group-hover/id:opacity-100")} />
                  )}
                </button>
              </InfoRow>
            </dl>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
