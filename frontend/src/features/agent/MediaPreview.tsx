import { useQueries, useQuery } from "@tanstack/react-query";
import { FileWarning, FolderOpen, Loader2, Music } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, getAsset, type Asset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { AudioPlayerBar, VideoPlayer } from "@/components/app/media-playback";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { gotoAsset } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

/**
 * 媒体预览卡:按素材 kind 渲染图/视频/音频,让智能体「返回」的素材在聊天里可见可播。
 *
 * 两处用它:工具行的明细(这一步碰过的素材)和一轮回答的结果区(这一轮做出来的,见 turnOutputs)。
 * 结果区的卡多一颗「在素材库中打开」(`reveal`)—— 那是这一轮交出来的东西,下一步多半是去素材库接着用它;
 * 工具行明细里那张多半是用户自己的原图,不必再指一遍路。
 */
function MediaPreview({ assetId, gallery, reveal }: { assetId: string; gallery?: ImagePreviewItem[]; reveal: boolean }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const asset = useQuery({
    queryKey: assetKeys.detail(assetId),
    queryFn: () => getAsset(assetId),
    staleTime: 60_000,
    retry: false,
  });
  if (asset.isLoading) {
    return (
      <div className="m-0 flex max-w-[240px] items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-2 text-ui-xs text-muted-foreground">
        <Loader2 size={13} className="animate-mosael-spin" />
      </div>
    );
  }
  //: 取不到的由 MediaPreviewGrid 统一收成一行,不在这里各画一张灰块(见那边的说明)。
  if (asset.isError || !asset.data) return null;
  const src = asset.data.kind === "image" ? assetPreviewUrl(asset.data.id) : assetFileUrl(asset.data.id);
  return (
    <figure className="group/media relative m-0 flex max-w-[240px] flex-col gap-1" data-media-preview={asset.data.id}>
      {asset.data.kind === "image" ? (
        <IconButton
          unstyled
          label={asset.data.name}
          className="block cursor-zoom-in border-0 bg-transparent p-0 focus-visible:rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          //: 点开不是孤零零一张 —— 同一批里的全部图/视频装进画廊,
          //: 灯箱里可以左右翻(单张结果时 gallery 为空,行为和原来一样)。
          onClick={() => openImagePreview({ src, title: asset.data.name, gallery })}
        >
          <img className="max-h-[200px] w-full rounded-lg border border-border bg-black object-contain" src={src} alt={asset.data.name} loading="lazy" />
        </IconButton>
      ) : asset.data.kind === "video" ? (
        //: 不用原生 controls —— 全站共享的 VideoPlayer(画板节点、大图灯箱同一副面孔)。
        //: 卡片尺寸与图/音频对齐(240×135):播放器悬停出控件,静止时压一枚大播放键。
        //: 播放器右下角的「全屏」开的是同一个灯箱(和这一批的图一起左右翻),不是浏览器原生全屏。
        <VideoPlayer
          assetSrc={src}
          className="h-[135px] w-[240px] rounded-lg border border-border"
          onExpand={() => openImagePreview({ src, title: asset.data.name, video: true, gallery })}
        />
      ) : asset.data.kind === "audio" ? (
        //: 不用原生 controls(各家各样、不吃主题)—— 全站共享的音频条,画板节点也是它。
        //: **卡片轮廓与图/视频对齐**(同宽同高):音频没有画面,但一条 40px 的瘦条夹在一排
        //: 200px 高的卡片中间,读着像渲染坏了。上面摆一枚音符占住画面位,控件条压在底部。
        <div className="flex h-[135px] w-[240px] flex-col rounded-lg border border-border bg-muted">
          <div className="grid min-h-0 flex-1 place-items-center text-muted-foreground">
            <Music size={22} className="opacity-50" />
          </div>
          <AudioPlayerBar src={src} showIcon={false} className="h-10 shrink-0 border-t border-border" />
        </div>
      ) : (
        <div className="m-0 flex max-w-[240px] items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-2 text-ui-xs text-muted-foreground">
          <FileWarning size={13} /> {asset.data.name}
        </div>
      )}
      <Truncate as="figcaption" className="text-ui-xs text-muted-foreground">{asset.data.name}</Truncate>
      {reveal && (
        //: 悬停才显形,压在画面右上角 —— 常态下画面就是画面。键盘聚焦到它时也显形(focus-visible)。
        <IconButton
          label={t("agentOutputOpenInLibrary")}
          variant="secondary"
          size="icon-xs"
          className="absolute right-1.5 top-1.5 opacity-0 shadow-sm transition-opacity duration-100 focus-visible:opacity-100 group-hover/media:opacity-100"
          onClick={() => gotoAsset(asset.data.id)}
        >
          <FolderOpen />
        </IconButton>
      )}
    </figure>
  );
}

/**
 * 一批媒体。画廊在这里拼:每张卡各自查自己的素材,但点开图片时要把**这一批**里的图/视频一起交给灯箱,
 * 才能左右翻。
 */
export function MediaPreviewGrid({
  assetIds,
  reveal = false,
  className,
}: {
  assetIds: string[];
  /** 每张卡带一颗「在素材库中打开」(结果区用)。 */
  reveal?: boolean;
  className?: string;
}) {
  const t = useI18n();
  const queries = useQueries({
    queries: assetIds.map((id) => ({
      queryKey: assetKeys.detail(id),
      queryFn: () => getAsset(id),
      staleTime: 60_000,
      retry: false,
    })),
  });
  const gallery: ImagePreviewItem[] = queries
    .map((query) => query.data)
    .filter((asset): asset is Asset => Boolean(asset))
    .filter((asset) => asset.kind === "image" || asset.kind === "video")
    .map((asset) => ({
      src: asset.kind === "image" ? assetPreviewUrl(asset.id) : assetFileUrl(asset.id),
      title: asset.name,
      video: asset.kind === "video",
    }));
  /**
   * **取不到的不占一张卡。**
   *
   * 聊天记录逐字留着工具结果,而里面的素材 id 是**当时的事实**:后来在素材库里删掉几个,
   * 那条旧消息下面就挂出一片和成功卡一样大的灰块 —— 一次 42 步的长对话能挂出十几张,
   * 看上去像"坏了一大片",而它说的只是"这些东西你后来删了"。
   *
   * 所以失败的收成一行小字。不完全藏起来:一份素材凭空消失和一份从来没生成出来,
   * 对着历史记录排查时是两件事。
   */
  const resolved = assetIds.filter((_, index) => queries[index].data);
  const missing = queries.filter((query) => query.isError).length;
  if (resolved.length === 0 && missing === 0) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {resolved.map((id) => (
        <MediaPreview key={id} assetId={id} gallery={gallery} reveal={reveal} />
      ))}
      {missing > 0 && (
        <span className="flex items-center gap-1 text-ui-xs text-muted-foreground">
          <FileWarning size={12} /> {t("agentMediaDeleted").replace("{n}", String(missing))}
        </span>
      )}
    </div>
  );
}
