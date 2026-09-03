import React from "react";
import { AudioLines, Pause, X } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, assetThumbnailUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";

/**
 * 生成节点素材槽里的紧凑预览。
 *
 * 类型必须一路带到渲染层：图片与视频可以共用缩略图，但视频打开灯箱时要声明 `video`；音频既没有
 * 缩略图，也不该进入图片灯箱，所以在原位提供播放/暂停。把这段收成一个组件后，连线自动挂载、
 * 素材库手选与恢复旧表单都会走同一个分支，不会再有某条入口把音频 URL 塞给 `<img>`。
 */
export function SourceAssetSlotPreview({
  assetId,
  kind,
  label,
  onRemove,
}: {
  assetId: string;
  kind: "image" | "video" | "audio";
  label: string;
  onRemove: () => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = React.useState(false);
  const previewLabel = t("boardPreviewSource").replace("{name}", label);
  const playLabel = t(playing ? "boardPauseSource" : "boardPlaySource").replace("{name}", label);

  const preview = kind === "audio" ? (
    <button
      type="button"
      aria-label={playLabel}
      title={playLabel}
      aria-pressed={playing}
      onClick={() => {
        const audio = audioRef.current;
        if (!audio) return;
        if (playing) {
          audio.pause();
          setPlaying(false);
          return;
        }
        void audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      }}
      className="grid h-8 w-8 place-items-center rounded-md border border-border bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground"
    >
      {playing ? <Pause size={13} /> : <AudioLines size={14} />}
      <audio ref={audioRef} src={assetFileUrl(assetId)} preload="metadata" onEnded={() => setPlaying(false)} />
    </button>
  ) : (
    <button
      type="button"
      aria-label={previewLabel}
      title={previewLabel}
      onClick={() =>
        openImagePreview({
          src: kind === "video" ? assetFileUrl(assetId) : assetPreviewUrl(assetId),
          title: label,
          ...(kind === "video" ? { video: true } : {}),
        })
      }
      className="block h-8 w-8 cursor-zoom-in overflow-hidden rounded-md border border-border transition-colors hover:border-border-strong"
    >
      <img src={assetThumbnailUrl(assetId)} alt="" className="h-full w-full object-cover" />
    </button>
  );

  return (
    <span className="group/thumb relative shrink-0">
      {preview}
      <button
        type="button"
        aria-label={`${t("boardRemove")}${label}`}
        title={t("boardRemove")}
        onClick={onRemove}
        className="absolute -right-1 -top-1 grid h-4 w-4 cursor-pointer place-items-center rounded-full border border-border bg-panel text-muted-foreground opacity-0 shadow-sm transition-opacity hover:border-destructive hover:text-destructive group-hover/thumb:opacity-100"
      >
        <X size={9} />
      </button>
    </span>
  );
}
