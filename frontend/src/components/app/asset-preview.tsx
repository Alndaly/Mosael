import React from "react";
import { Paperclip } from "lucide-react";

import { assetFileUrl } from "@/api/client";
import { useImagePreview } from "@/components/app/image-preview";

/**
 * 一个素材的行内预览:图出图、视频出播放器、音频出音轨,其余退回文件胶囊。
 *
 * 抽出来是因为有两个消费方 —— 智能体对话里的附件,和工作流执行历史里的产物。此前只有前者
 * 有预览,后者把 `asset_id: 535f288eaeb4…` 一串裸 id 直接铺在文本块里:同一次生成,在对话里
 * 是一张图,在历史里是一串十六进制,用户还得自己去素材库翻。
 *
 * 尺寸交给调用方(`className`):对话气泡里可以铺得大些,历史面板那种窄列要压扁。
 */
export function AssetInlinePreview({
  assetId,
  name,
  kind,
  className,
}: {
  assetId: string;
  name: string;
  kind: string;
  /** 覆盖媒体元素的尺寸约束。默认按对话气泡的刻度。 */
  className?: string;
}) {
  const { openImagePreview } = useImagePreview();
  const src = assetFileUrl(assetId);

  if (kind === "image") {
    return (
      <button
        type="button"
        title={name}
        className="block w-fit max-w-full cursor-zoom-in overflow-hidden rounded-lg border border-border bg-black p-0"
        onClick={() => openImagePreview({ src, title: name })}
      >
        <img
          src={src}
          alt={name}
          loading="lazy"
          className={className ?? "block max-h-[180px] w-auto max-w-full object-contain"}
        />
      </button>
    );
  }
  if (kind === "video") {
    return (
      <video
        src={src}
        controls
        preload="metadata"
        className={className ?? "max-h-[200px] max-w-full rounded-lg border border-border bg-black"}
      />
    );
  }
  if (kind === "audio") {
    return <audio src={src} controls preload="metadata" className={className ?? "w-[260px] max-w-full"} />;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-[5px] rounded-lg border border-border bg-panel px-2 py-1 text-[11.5px] text-muted-foreground">
      <Paperclip size={12} className="shrink-0" />
      <span className="min-w-0 truncate" title={name}>
        {name}
      </span>
    </span>
  );
}
