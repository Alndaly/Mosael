import React from "react";
import { Maximize2, Paperclip } from "lucide-react";

import { assetFileUrl, assetPreviewUrl } from "@/api/client";
import { cn } from "@/lib/utils";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { AudioPlayerBar } from "@/components/app/media-playback";

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
  lazy = true,
  plain = false,
  previewOnClick = true,
  onNaturalSize,
  gallery,
}: {
  assetId: string;
  name: string;
  kind: string;
  /** 覆盖媒体元素的尺寸约束。默认按对话气泡的刻度。 */
  className?: string;
  /** 去掉自带的边框与黑底。画布节点里由外层容器统一收边,元素各带一圈边框会显得碎。 */
  plain?: boolean;
  /** 点一下开大图预览。**画布上要关掉** —— 那里点一下的意思是「选中这个节点」,
   *  被预览抢走的话,节点的操作条和表单就都弹不出来了。 */
  previewOnClick?: boolean;
  /** 懒加载。**画布节点里必须关掉**:React Flow 的视口是 transform 变换过的,浏览器据此
   *  判断"还没进视野"而迟迟不发请求,图片就一直是 0×0,节点上看着像没产出。 */
  lazy?: boolean;
  /** 媒体的**自然尺寸**加载出来时报一次。画布节点用它把自己的宽高比校正成画面的比例 ——
   *  不校正的话 16:9 的片子摆在 1.6:1 的框里,上下各留一条黑边。可选:别的消费方不关心。 */
  onNaturalSize?: (width: number, height: number) => void;
  /** 同一聊天/生成批次里的媒体。react-photo-view 用它提供左右翻页与计数。 */
  gallery?: ImagePreviewItem[];
}) {
  const { openImagePreview } = useImagePreview();
  const src = kind === "image" ? assetPreviewUrl(assetId) : assetFileUrl(assetId);
  const openPreview = () =>
    openImagePreview({
      src,
      title: name,
      ...(kind === "video" ? { video: true } : {}),
      ...(gallery?.length ? { gallery } : {}),
    });

  if (kind === "image") {
    const picture = (
      <img
        src={src}
        alt={name}
        title={previewOnClick ? undefined : name}
        loading={lazy ? "lazy" : "eager"}
        className={className ?? "block max-h-[180px] w-auto max-w-full object-contain"}
        onLoad={(event) => {
          const img = event.currentTarget;
          if (img.naturalWidth && img.naturalHeight) onNaturalSize?.(img.naturalWidth, img.naturalHeight);
        }}
      />
    );
    //: **不点开预览的时候连按钮都不要**。只把 onClick 摘掉的话,外面那层按钮和它的放大镜
    //: 光标还在 —— 鼠标一悬上去就说「这儿能点开」,点了却什么都不发生。
    if (!previewOnClick) return picture;
    return (
      <button
        type="button"
        title={name}
        className={cn(
          "block max-w-full cursor-zoom-in overflow-hidden p-0",
          plain ? "w-full border-0 bg-transparent" : "w-fit rounded-lg border border-border bg-black",
        )}
        onClick={openPreview}
      >
        {picture}
      </button>
    );
  }
  if (kind === "video") {
    return (
      <div className="relative w-fit max-w-full">
        {/* nodrag:播放条要能点、能拖进度,不能让画布把 pointerdown 抢去拖节点。 */}
        <video
          src={src}
          controls
          preload="metadata"
          className={cn(
            "nodrag",
            className ?? (plain ? "max-w-full bg-black" : "max-h-[200px] max-w-full rounded-lg border border-border bg-black"),
          )}
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            if (video.videoWidth && video.videoHeight) onNaturalSize?.(video.videoWidth, video.videoHeight);
          }}
        />
        {previewOnClick && (
          <button
            type="button"
            title={name}
            aria-label={name}
            className="nodrag absolute right-1.5 top-1.5 inline-flex size-7 cursor-zoom-in items-center justify-center rounded-full border border-white/20 bg-black/55 p-0 text-white backdrop-blur-sm hover:bg-black/75"
            onClick={openPreview}
          >
            <Maximize2 size={13} />
          </button>
        )}
      </div>
    );
  }
  if (kind === "audio") {
    //: 不用原生 controls —— 全站共享的音频条(media-playback)。不挂 nodrag:播放键点一下
    //: 不是拖动,进度条的 nodrag 写在 Scrubber 自己内部。
    return <AudioPlayerBar src={src} className={cn("h-10 rounded-lg border border-border bg-panel", className ?? "w-[260px] max-w-full")} />;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-[5px] rounded-lg border border-border bg-panel px-2 py-1 text-ui-xs text-muted-foreground">
      <Paperclip size={12} className="shrink-0" />
      <span className="min-w-0 truncate" title={name}>
        {name}
      </span>
    </span>
  );
}
