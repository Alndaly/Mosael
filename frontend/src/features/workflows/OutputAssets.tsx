import React from "react";
import { useQueries } from "@tanstack/react-query";

import { getAsset, type Asset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { AssetInlinePreview, assetGallery } from "@/components/app/asset-preview";
import type { ImagePreviewItem } from "@/components/app/image-preview";
import { Truncate } from "@/components/ui/truncate";
import type { AssetOutput } from "@/features/workflows/runSteps";
import { cn } from "@/lib/utils";

/**
 * 一次运行产出的素材,**带着它们自己的名字**。画布节点和检查器里的「本次产出」共用这一份。
 *
 * 此前是两份:节点卡片里一份、检查器里一份,各带一张"什么类型配什么尺寸"的表。两份都把
 * 输出的名字丢了(只传 id 列表),于是「分离人声与背景音」跑完摆出两个一模一样的音频条,
 * 哪条是人声只能靠点开听;而检查器那份的表是照着视频写的 —— 音频落进 `h-[78px] bg-black`,
 * 成了一个黑方块里嵌一条播放器。
 *
 * 尺寸按**素材种类**给,不按调用方给:一条音频要的是横向长度(进度条),一张图要的是高度。
 * 两种密度只差在给多少高度 —— 画布上一张卡片总共才两百来像素宽。
 */

/** 每种素材在两种密度下占多大。音频两处一样:它是一条,不是一块。 */
const PREVIEW_CLASS: Record<string, { node: string; panel: string }> = {
  image: { node: "block h-[96px] w-full object-contain", panel: "block max-h-[168px] w-full object-contain" },
  video: { node: "h-[96px] w-full", panel: "h-[150px] w-full" },
  audio: { node: "w-full", panel: "w-full" },
};

export function OutputAssets({
  items,
  density,
  className,
  gallery,
}: {
  items: AssetOutput[];
  density: "node" | "panel";
  className?: string;
  /** 点开大图后左右翻的那一组。执行历史给的是**这一整次运行**的产出(一步一步往下翻);不给就是这一步自己的几份。 */
  gallery?: ImagePreviewItem[];
}) {
  // 最多两份:画布上的卡片是张名片,不是相册。检查器里也够用 —— 再多的走执行历史。
  const shown = items.slice(0, 2);
  const assets = useQueries({
    queries: shown.map((item) => ({
      queryKey: assetKeys.detail(item.assetId),
      queryFn: () => getAsset(item.assetId),
      staleTime: 60_000,
      retry: false,
    })),
  });
  // 素材可能已经被删掉 —— 取不到就不画,这是正常路径而不是错误。
  const ready = shown
    .map((item, index) => ({ item, asset: assets[index]?.data }))
    .filter((pair): pair is { item: AssetOutput; asset: Asset } => Boolean(pair.asset));
  if (ready.length === 0) return null;

  // **并排只给画面**:缩略图并排看得清,而音频条并排之后每条只剩一半宽,进度条几乎点不中。
  const sideBySide = ready.length > 1 && ready.every((pair) => pair.asset.kind !== "audio");
  const group = gallery ?? assetGallery(ready.map((pair) => pair.asset));
  // 名字在**分不清的时候**才占一行:一份产出时节点标题已经说了它是什么;两份摆在一起,
  // 「哪个是哪个」就是这一刻唯一要回答的问题。检查器里一律带 —— 那儿每一行本来就报名字。
  const named = density === "panel" || ready.length > 1;

  return (
    <div className={cn("grid min-w-0 gap-px", sideBySide && "grid-flow-col auto-cols-fr", className)}>
      {ready.map(({ item, asset }) => {
        // 画面通栏(卡片本来就不带内边距),音频条留边 —— 它自带一圈边框,贴着卡片边缘会
        // 读成"卡片裂了一道缝"。
        const bleed = asset.kind !== "audio";
        return (
        <figure
          key={item.key || item.assetId}
          className={cn("m-0 grid min-w-0 gap-1", !bleed && density === "node" && "px-2.5 py-2")}
        >
          {/* 检查器里名字后面跟稳定 key(和下面文字产出那几行一样):它是 `{{节点.key}}` 里要写的那个词。
              卡片上只报名字 —— 位置不够,key 在检查器里看。 */}
          {named && item.label && (
            <figcaption className={cn("flex min-w-0 items-baseline gap-1 text-ui-2xs text-muted-foreground", bleed && "px-3 pt-1.5")}>
              <Truncate>{item.label}</Truncate>
              {density === "panel" && item.key && item.key !== item.label && (
                <span className="shrink-0 font-mono">{item.key}</span>
              )}
            </figcaption>
          )}
          <AssetInlinePreview
            assetId={asset.id}
            name={asset.name || asset.original_filename}
            kind={asset.kind}
            lazy={false}
            plain
            //: 画布上点一下是「选中这个节点」(检查器跟着出来),看大图走角上那颗;检查器、历史里点图就开。
            preview={density === "node" ? "button" : "click"}
            gallery={group}
            className={PREVIEW_CLASS[asset.kind]?.[density]}
          />
        </figure>
        );
      })}
    </div>
  );
}
