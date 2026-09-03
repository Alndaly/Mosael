import * as React from "react";
import { Check, Copy, FileAudio, Maximize2 } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useImagePreview } from "@/components/app/image-preview";
import { AudioPlayerBar } from "@/components/app/media-playback";
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
    <div className="grid grid-cols-[76px_minmax(0,1fr)] items-baseline gap-3">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 text-ui-sm text-foreground [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/**
 * 素材详情预览:左侧媒体(图片可点开全屏、视频/音频内联播放),右侧完整元数据(类型/尺寸/时长/
 * 帧率/来源/标签/原始文件名/创建时间/ID)。图片也先进这张卡,而不是直接跳全屏,才看得到数据。
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
      <DialogContent className="w-[min(960px,calc(100vw-32px))] max-w-[calc(100vw-32px)] gap-0 overflow-hidden p-0">
        <div className="grid max-h-[86vh] grid-cols-1 md:grid-cols-[minmax(0,1fr)_300px]">
          {/* 媒体区 */}
          <div className="relative grid min-h-[240px] place-items-center overflow-hidden bg-[#0b0b0d] md:min-h-[420px]">
            {asset.kind === "video" && (
              <video className="max-h-[86vh] max-w-full" src={src} controls autoPlay playsInline />
            )}
            {asset.kind === "image" && (
              <button
                type="button"
                title={t("assetClickToZoom")}
                className="group/zoom relative grid h-full w-full cursor-zoom-in place-items-center border-0 bg-transparent p-0"
                onClick={() => openImagePreview({ src, title: asset.name })}
              >
                <img className="max-h-[86vh] max-w-full object-contain" src={src} alt={asset.name} />
                <span className="pointer-events-none absolute bottom-2.5 right-2.5 inline-flex items-center gap-1 rounded-md bg-[rgba(10,12,15,0.7)] px-2 py-1 text-ui-xs text-white opacity-0 transition-opacity duration-100 group-hover/zoom:opacity-100">
                  <Maximize2 size={12} /> {t("assetClickToZoom")}
                </span>
              </button>
            )}
            {asset.kind === "audio" && (
              <div className="grid w-full max-w-[420px] justify-items-center gap-4 px-6">
                <span className="grid h-16 w-16 place-items-center rounded-full bg-[rgb(255_255_255/0.06)] text-muted-foreground">
                  <FileAudio size={26} />
                </span>
                <AudioPlayerBar
                  src={src}
                  autoPlay
                  showIcon={false}
                  className="h-12 rounded-xl border border-[rgb(255_255_255/0.1)] bg-[rgb(255_255_255/0.05)] px-3"
                />
              </div>
            )}
          </div>

          {/* 信息区 */}
          <div className="grid content-start gap-3 overflow-y-auto border-t border-border bg-panel p-4 md:border-l md:border-t-0">
            <DialogTitle className="break-all text-[15px] font-[650] leading-snug">{asset.name}</DialogTitle>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="secondary">{kindLabel}</Badge>
              <Badge variant="outline">{sourceLabel}</Badge>
            </div>
            {tags.length > 0 && (
              <div className="grid gap-1">
                <span className="text-ui-xs text-muted-foreground">{t("assetTagsLabel")}</span>
                <div className="flex flex-wrap gap-1">
                  {tags.map((tag) => (
                    <span
                      className="inline-flex items-center rounded-full border border-border bg-panel-subtle px-2 py-px text-ui-xs text-muted-foreground"
                      key={tag}
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <dl className="m-0 grid gap-2 border-t border-border pt-3">
              <InfoRow label={t("assetType")}>{kindLabel}</InfoRow>
              {width > 0 && height > 0 && (
                <InfoRow label={t("assetDimensions")}>
                  <span className="font-mono tabular-nums">{width}×{height}</span>
                  <span className="ml-1.5 text-muted-foreground">({aspectRatio(width, height)})</span>
                </InfoRow>
              )}
              {duration != null && duration > 0 && (
                <InfoRow label={t("duration")}>
                  <span className="font-mono tabular-nums">{formatTimecode(duration)}</span>
                </InfoRow>
              )}
              {asset.kind === "video" && fps > 0 && (
                <InfoRow label={t("assetFps")}>
                  <span className="font-mono tabular-nums">{Math.round(fps)}fps</span>
                </InfoRow>
              )}
              <InfoRow label={t("assetSource")}>{sourceLabel}</InfoRow>
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
