import React from "react";
import { Paperclip } from "lucide-react";

import { assetFileUrl, assetPreviewUrl } from "@/api/client";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { AudioPlayerBar, VideoPlayer } from "@/components/app/media-playback";
import { ViewFullSizeButton } from "@/components/app/view-full-size";

/**
 * 一份素材在灯箱里是哪一项 —— 图走预览地址(HEIC 这类浏览器解不了的原图,后端转好了一份),视频走原文件、
 * 标上 `video`(同一个灯箱换成播放器)。音频、文档没有画面,不进灯箱:返回 null。
 *
 * **点开的那一项和画廊里的那一项必须是同一个地址**:灯箱按 src 找「从第几张开始」,对不上就从第一张开始 ——
 * 点的是第三张,打开的却是第一张。所以缩略图点开时也走这里,不各写一份。
 */
export function assetPreviewItem(asset: { id: string; kind: string; name?: string | null; original_filename?: string | null }): ImagePreviewItem | null {
  const title = asset.name || asset.original_filename || undefined;
  if (asset.kind === "image") return { src: assetPreviewUrl(asset.id), title };
  if (asset.kind === "video") return { src: assetFileUrl(asset.id), title, video: true };
  return null;
}

/** 一组素材里能进灯箱的那些,按原来的先后。 */
export function assetGallery(assets: readonly Parameters<typeof assetPreviewItem>[0][]): ImagePreviewItem[] {
  return assets.flatMap((asset) => assetPreviewItem(asset) ?? []);
}

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
  preview = "click",
  onNaturalSize,
  gallery,
  imageFallback,
  onOpenFile,
}: {
  assetId: string;
  name: string;
  kind: string;
  /** 覆盖媒体元素的尺寸约束。默认按对话气泡的刻度。 */
  className?: string;
  /** 去掉自带的边框与黑底。画布节点里由外层容器统一收边,元素各带一圈边框会显得碎。 */
  plain?: boolean;
  /**
   * 怎么开大图。
   * - `click`:点图就开(对话气泡、检查器 —— 那里点一下没有别的意思)。
   * - `button`:图不接管点击,角上压一颗「看大图」(工作流画布上的节点 —— 点一下的意思是「选中这个节点」,
   *   被预览抢走的话,节点的检查器就弹不出来了)。
   * - `off`:不开(画板的图片格:看大图走操作条上的「预览」;能力面板里那张认脸用的小图)。
   * 视频三种都由播放器自己的「全屏」那颗来开,`off` 时它退回浏览器原生全屏。
   */
  preview?: "click" | "button" | "off";
  /** 懒加载。**画布节点里必须关掉**:React Flow 的视口是 transform 变换过的,浏览器据此
   *  判断"还没进视野"而迟迟不发请求,图片就一直是 0×0,节点上看着像没产出。 */
  lazy?: boolean;
  /** 媒体的**自然尺寸**加载出来时报一次。画布节点用它把自己的宽高比校正成画面的比例 ——
   *  不校正的话 16:9 的片子摆在 1.6:1 的框里,上下各留一条黑边。可选:别的消费方不关心。 */
  onNaturalSize?: (width: number, height: number) => void;
  /** 同一聊天/生成批次里的媒体。react-photo-view 用它提供左右翻页与计数。 */
  gallery?: ImagePreviewItem[];
  /** Scene cards can explain a missing preview instead of displaying a broken image. */
  imageFallback?: React.ReactNode;
  /** 文档这类只剩文件胶囊的素材,点开怎么看。给了胶囊就是一颗按钮;没给就只是个标签。
   *  详情弹窗住在素材功能里,这一层不认识它,所以由调用方传进来。 */
  onOpenFile?: () => void;
}) {
  const { openImagePreview } = useImagePreview();
  const [imageFailure, setImageFailure] = React.useState({ assetId: "", stage: 0 });
  const stage = imageFailure.assetId === assetId ? imageFailure.stage : 0;
  const src = kind === "image" && stage === 0 ? assetPreviewUrl(assetId) : assetFileUrl(assetId);
  const openPreview = () =>
    openImagePreview({
      src,
      title: name,
      ...(kind === "video" ? { video: true } : {}),
      ...(gallery?.length ? { gallery } : {}),
    });

  if (kind === "image") {
    if (stage >= 2 && imageFallback) return <>{imageFallback}</>;
    const picture = (
      <img
        src={src}
        onError={() => { if (stage < 2) setImageFailure({ assetId, stage: stage + 1 }); }}
        alt={name}
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
    if (preview === "off") return <Hint label={name}>{picture}</Hint>;
    if (preview === "button") {
      return (
        <span className="group/preview relative block min-w-0">
          <Hint label={name}>{picture}</Hint>
          <ViewFullSizeButton name={name} onOpen={openPreview} className="right-1.5 top-1.5" />
        </span>
      );
    }
    return (
      <Hint label={name}>
        <button
          type="button"
          className={cn(
            "block max-w-full cursor-zoom-in overflow-hidden p-0",
            plain ? "w-full border-0 bg-transparent" : "w-fit rounded-lg border border-border bg-black",
          )}
          onClick={openPreview}
        >
          {picture}
        </button>
      </Hint>
    );
  }
  if (kind === "video") {
    return (
      <VideoPlayer
        key={assetId}
        assetSrc={src}
        compact
        className={cn("max-w-full", className ?? "h-[160px] w-[260px] rounded-lg")}
        onNaturalSize={onNaturalSize}
        onExpand={preview === "off" ? undefined : openPreview}
      />
    );
  }
  if (kind === "audio") {
    //: 不用原生 controls —— 全站共享的音频条(media-playback)。不挂 nodrag:播放键点一下
    //: 不是拖动,进度条的 nodrag 写在 Scrubber 自己内部。
    return <AudioPlayerBar src={src} className={cn("h-10 rounded-lg border border-border bg-panel", className ?? "w-[260px] max-w-full")} />;
  }
  const chip = "inline-flex max-w-full items-center gap-[5px] rounded-lg border border-border bg-panel px-2 py-1 text-ui-xs text-muted-foreground";
  const label = (
    <>
      <Paperclip size={12} className="shrink-0" />
      <Truncate>{name}</Truncate>
    </>
  );
  if (onOpenFile) {
    return (
      <button type="button" className={cn(chip, "cursor-pointer hover:bg-control hover:text-foreground")} onClick={onOpenFile}>
        {label}
      </button>
    );
  }
  return <span className={chip}>{label}</span>;
}
