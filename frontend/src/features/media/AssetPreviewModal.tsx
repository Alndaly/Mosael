import * as React from "react";
import { ArrowLeft, Check, Copy, Maximize2 } from "lucide-react";
import { toast } from "sonner";

import { assetFileUrl, assetPreviewUrl, getAsset, type Asset } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useImagePreview } from "@/components/app/image-preview";
import { MediaPreviewPlayer } from "@/components/app/MediaPreviewPlayer";
import { AssetEntitiesList } from "@/features/entities/AssetEntities";
import { AssetLineageList } from "@/features/media/AssetLineage";
import { assetOriginKey, showsContainsAi } from "@/features/media/assetOrigin";
import { cn } from "@/lib/utils";
import { assetKindKey } from "@/lib/assetKinds";
import { DocumentReader } from "@/features/media/DocumentReader";
import { documentFacts } from "@/lib/assetKinds";
import { formatTimecode, parseServerTime } from "@/lib/time";

/** 后端时间是无时区的 UTC ISO 串;补 Z 再按本地时区显示到分钟。 */
function formatDateTime(iso: string): string {
  const date = parseServerTime(iso);
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
  // 顺着「来自」点进去看的出处:栈顶是正在看的那一份,「返回上一份」退一格。换了一份素材就清空。
  // 点的那一刻取一次就够(不进查询缓存):这张弹窗在很多地方是独立挂的,不该为了它要求外面有查询上下文。
  const [trail, setTrail] = React.useState<Asset[]>([]);
  const shownId = trail.at(-1)?.id ?? asset?.id;
  React.useEffect(() => {
    setTrail([]);
  }, [asset?.id]);
  React.useEffect(() => {
    setCopied(false);
  }, [shownId]);

  if (!asset) return <Dialog open={false} onOpenChange={(open) => !open && onClose()} />;

  const shown = trail.at(-1) ?? asset;
  const openSource = (id: string) => {
    getAsset(id).then(
      (source) => setTrail((now) => [...now, source]),
      (error: unknown) => toast.error(errorText(error)),
    );
  };
  const media = shown.media_info ?? {};
  const width = Number(media.width) || 0;
  const height = Number(media.height) || 0;
  const fps = Number(media.fps) || 0;
  const duration = media.duration != null ? Number(media.duration) : null;
  // Chromium does not decode HEIC/HEIF. Images must use the backend's browser-compatible
  // representation; video and audio still stream the untouched original file.
  const src = shown.kind === "image" ? assetPreviewUrl(shown.id) : assetFileUrl(shown.id);
  const kindLabel = t(assetKindKey(shown.kind));
  const tags = shown.tags ?? [];

  const copyId = () => {
    void navigator.clipboard.writeText(shown.id).then(() => {
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
      <DialogContent className={cn("w-[min(1040px,calc(100vw-32px))] max-w-[calc(100vw-32px)] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0", shown.kind === "audio" ? "h-[min(480px,86dvh)] md:w-[min(880px,calc(100vw-32px))]" : shown.kind === "document" ? "h-[min(900px,90dvh)] md:w-[min(1480px,calc(100vw-32px))]" : "h-[min(720px,86dvh)]")}>
        <header className="grid min-w-0 gap-2 border-b border-divider px-5 py-4 pr-14">
          {trail.length > 0 && (
            <button
              type="button"
              className="inline-flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-ui-xs text-muted-foreground hover:text-foreground"
              onClick={() => setTrail((now) => now.slice(0, -1))}
            >
              <ArrowLeft size={12} /> {t("assetLineageBack")}
            </button>
          )}
          <DialogTitle className="min-w-0 max-h-24 overflow-y-auto whitespace-normal text-ui-lg leading-snug [overflow-wrap:anywhere]">{shown.name}</DialogTitle>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{kindLabel}</Badge>
            <Badge variant="outline">{t(assetOriginKey(shown))}</Badge>
            {showsContainsAi(shown) && <Badge variant="outline">{t("mediaSourceContainsAi")}</Badge>}
          </div>
        </header>
        <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(200px,1fr)_minmax(0,180px)] md:grid-cols-[minmax(0,1fr)_300px] md:grid-rows-[minmax(0,1fr)]">
          <div className="relative grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden bg-workspace-subtle">
            {(shown.kind === "video" || shown.kind === "audio") && (
              <MediaPreviewPlayer key={shown.id} kind={shown.kind} src={src} assetId={shown.id} />
            )}
            {shown.kind === "document" && <DocumentReader assetId={shown.id} />}
            {shown.kind === "image" && (
              // 悬停时右下角那块「点击查看大图」就是说明,不再另挂一条。
              <button
                type="button"
                className="group/zoom relative grid h-full min-h-0 w-full min-w-0 cursor-zoom-in place-items-center border-0 bg-transparent p-4"
                onClick={() => openImagePreview({ src, title: shown.name })}
              >
                <img className="h-full min-h-0 w-full min-w-0 object-contain" src={src} alt={shown.name} />
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
              {shown.kind !== "image" && duration != null && duration > 0 && (
                <InfoRow label={t("duration")}>
                  <span className="font-mono tabular-nums">{formatTimecode(duration)}</span>
                </InfoRow>
              )}
              {shown.kind === "video" && fps > 0 && (
                <InfoRow label={t("assetFps")}>
                  <span className="font-mono tabular-nums">{Math.round(fps)}fps</span>
                </InfoRow>
              )}
              {shown.kind === "document" && (
                <InfoRow label={t("assetFormat")}>
                  <span className="font-mono tabular-nums">{documentFacts(shown)}</span>
                </InfoRow>
              )}
              {shown.original_filename && shown.original_filename !== shown.name && (
                <InfoRow label={t("assetOriginalName")}>{shown.original_filename}</InfoRow>
              )}
              {/* 它是从哪几份、经过什么操作做出来的(截取、转 GIF、导出成片……),点一下看那一份。 */}
              {(shown.derived_from?.length ?? 0) > 0 && (
                <InfoRow label={t("assetLineageTitle")}>
                  <AssetLineageList assetId={shown.id} onOpen={openSource} />
                </InfoRow>
              )}
              {/* 这张图是哪些资产的参考图(ADR 0027)。删这份素材时,它们各少一张参考图。 */}
              {(shown.kind === "image" || shown.kind === "video") && (
                <InfoRow label={t("assetEntitiesTitle")}>
                  <AssetEntitiesList asset={shown} />
                </InfoRow>
              )}
              {shown.created_at && (
                <InfoRow label={t("assetCreated")}>
                  <span className="font-mono tabular-nums">{formatDateTime(shown.created_at)}</span>
                </InfoRow>
              )}
              <InfoRow label="ID">
                <Hint label={copied ? t("assetIdCopied") : t("assetCopyId")}>
                  <button
                    type="button"
                    onClick={copyId}
                    className="group/id inline-flex max-w-full items-center gap-1 rounded-sm text-left font-mono text-ui-xs tabular-nums text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <Truncate>{shown.id}</Truncate>
                    {copied ? (
                      <Check size={12} className="shrink-0 text-success" />
                    ) : (
                      <Copy size={12} className={cn("shrink-0 opacity-0 transition-opacity group-hover/id:opacity-100")} />
                    )}
                  </button>
                </Hint>
              </InfoRow>
            </dl>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
