import React from "react";
import { useQueries } from "@tanstack/react-query";

import { getAsset, type Asset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
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
 *
 * **一个口可以交好几份**(一次出两张的 ComfyUI 工作流,那个保存节点的口上是两张;宫格切分的那一串)。此前这里只认
 * 一个口一份,一串的整个不画;卡片上又只摆前两份 —— 维护者跑 batch 2 的工作流,「图 · 预览图像」那一格只看得到一张。
 * 现在按口分组:一份照原来那样摆,几份排成网格、名字后面报几张,摆不下的在最后一格写「+N」(点开大图能翻到全部)。
 */

/** 每种素材在两种密度下占多大。音频两处一样:它是一条,不是一块。 */
const PREVIEW_CLASS: Record<string, { node: string; panel: string }> = {
  image: { node: "block h-[96px] w-full object-contain", panel: "block max-h-[168px] w-full object-contain" },
  video: { node: "h-[96px] w-full", panel: "h-[150px] w-full" },
  audio: { node: "w-full", panel: "w-full" },
};
/** 一个口的几份排成网格时,每一格多大:缩略图裁成一样高,整张在大图里看。 */
const GRID_CLASS: Record<string, { node: string; panel: string }> = {
  image: { node: "block h-[72px] w-full object-cover", panel: "block h-[96px] w-full object-cover" },
  video: { node: "h-[72px] w-full", panel: "h-[96px] w-full" },
  audio: { node: "w-full", panel: "w-full" },
};
/** 一个口最多摆几格:卡片是张名片,不是相册;检查器宽一些。再多的点开大图翻,或者看执行历史。 */
const MAX_CELLS = { node: 4, panel: 6 } as const;
/** 卡片上最多摆几个口(检查器里每个口都摆 —— 那儿本来就是一个口一行)。 */
const MAX_GROUPS_ON_NODE = 2;

type Ready = { item: AssetOutput; asset: Asset };
type Group = { key: string; label: string; members: Ready[] };

/** 按口分组,保持先后。 */
function groupsOf(ready: Ready[]): Group[] {
  const groups: Group[] = [];
  for (const pair of ready) {
    const last = groups[groups.length - 1];
    if (last && last.key === pair.item.key) last.members.push(pair);
    else groups.push({ key: pair.item.key, label: pair.item.label, members: [pair] });
  }
  return groups;
}

/** 「2 张」/「3 份」:全是图说张,混着别的说份。 */
function countText(t: (key: MessageKey) => string, members: Ready[]): string {
  const key: MessageKey = members.every((pair) => pair.asset.kind === "image") ? "wfOutputImageCount" : "wfOutputFileCount";
  return t(key).replace("{n}", String(members.length));
}

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
  const t = useI18n();
  // 卡片上**同一份素材只摆一次**:「第一份产出」和那个保存节点的第一张是同一个文件,摆两遍就是一张重复的图。
  // 检查器里一个口一行地报(那儿要回答的是「这个口给了什么」),照摆。
  const entries = density === "node" ? items.filter((item, index) => items.findIndex((one) => one.assetId === item.assetId) === index) : items;
  const assets = useQueries({
    queries: entries.map((item) => ({
      queryKey: assetKeys.detail(item.assetId),
      queryFn: () => getAsset(item.assetId),
      staleTime: 60_000,
      retry: false,
    })),
  });
  // 素材可能已经被删掉 —— 取不到就不画,这是正常路径而不是错误。
  const ready = entries
    .map((item, index) => ({ item, asset: assets[index]?.data }))
    .filter((pair): pair is Ready => Boolean(pair.asset));
  const groups = groupsOf(ready).slice(0, density === "node" ? MAX_GROUPS_ON_NODE : undefined);
  if (groups.length === 0) return null;
  const group = gallery ?? assetGallery(groups.flatMap((one) => one.members.map((pair) => pair.asset)));

  if (groups.every((one) => one.members.length === 1)) {
    return <SingleAssets pairs={groups.map((one) => one.members[0])} density={density} className={className} gallery={group} />;
  }
  return (
    <div className={cn("grid min-w-0 gap-px", className)}>
      {groups.map((one) => (
        <GroupedAssets
          key={one.key}
          group={one}
          density={density}
          // 名字只在分不清的时候占一行;一个口好几份时那一行报几张 —— 一眼看出这一步交了几份
          named={density === "panel" || groups.length > 1 || one.members.length > 1}
          count={one.members.length > 1 ? countText(t, one.members) : ""}
          gallery={group}
        />
      ))}
    </div>
  );
}

/** 每个口一份:并排(画面)或上下(音频),两份摆在一起时各带名字。 */
function SingleAssets({
  pairs,
  density,
  className,
  gallery,
}: {
  pairs: Ready[];
  density: "node" | "panel";
  className?: string;
  gallery: ImagePreviewItem[];
}) {
  // **并排只给画面**:缩略图并排看得清,而音频条并排之后每条只剩一半宽,进度条几乎点不中。
  const sideBySide = pairs.length > 1 && pairs.every((pair) => pair.asset.kind !== "audio");
  // 名字在**分不清的时候**才占一行:一份产出时节点标题已经说了它是什么;两份摆在一起,
  // 「哪个是哪个」就是这一刻唯一要回答的问题。检查器里一律带 —— 那儿每一行本来就报名字。
  const named = density === "panel" || pairs.length > 1;
  return (
    // 两份并排一行;检查器里口多了(几个输出节点各一张)两列往下排,不挤成一排细条
    <div className={cn("grid min-w-0 gap-px", sideBySide && (pairs.length > 2 ? "grid-cols-2" : "grid-flow-col auto-cols-fr"), className)}>
      {pairs.map(({ item, asset }) => {
        // 画面通栏(卡片本来就不带内边距),音频条留边 —— 它自带一圈边框,贴着卡片边缘会
        // 读成"卡片裂了一道缝"。
        const bleed = asset.kind !== "audio";
        return (
          <figure
            key={item.key || item.assetId}
            className={cn("m-0 grid min-w-0 gap-1", !bleed && density === "node" && "px-2.5 py-2")}
          >
            {named && <Caption item={item} density={density} bleed={bleed} />}
            <AssetInlinePreview
              assetId={asset.id}
              name={asset.name || asset.original_filename}
              kind={asset.kind}
              lazy={false}
              plain
              //: 画布上点一下是「选中这个节点」(检查器跟着出来),看大图走角上那颗;检查器、历史里点图就开。
              preview={density === "node" ? "button" : "click"}
              gallery={gallery}
              className={PREVIEW_CLASS[asset.kind]?.[density]}
            />
          </figure>
        );
      })}
    </div>
  );
}

/** 一个口交的几份:名字后面报几张,画面排成网格(音频上下排),摆不下的在最后一格写「+N」。 */
function GroupedAssets({
  group,
  density,
  named,
  count,
  gallery,
}: {
  group: Group;
  density: "node" | "panel";
  named: boolean;
  count: string;
  gallery: ImagePreviewItem[];
}) {
  const shown = group.members.slice(0, MAX_CELLS[density]);
  const hidden = group.members.length - shown.length;
  const visual = shown.every((pair) => pair.asset.kind !== "audio");
  const first = shown[0].item;
  const single = shown.length === 1;
  return (
    <figure className="m-0 grid min-w-0 gap-1" data-output-group={group.key}>
      {named && <Caption item={first} density={density} bleed={visual} count={count} />}
      <div
        className={cn(
          "grid min-w-0 gap-px",
          //: 卡片上两列;检查器里两份两列、再多三列 —— 两张摆在三列里会空出一截
          visual && !single && (density === "node" || shown.length === 2 ? "grid-cols-2" : "grid-cols-3"),
          !visual && density === "node" && "gap-2 px-2.5 py-2",
        )}
      >
        {shown.map(({ item, asset }, index) => (
          <div key={`${item.key}:${asset.id}:${index}`} className="relative min-w-0">
            <AssetInlinePreview
              assetId={asset.id}
              name={asset.name || asset.original_filename}
              kind={asset.kind}
              lazy={false}
              plain
              preview={density === "node" ? "button" : "click"}
              gallery={gallery}
              className={(single ? PREVIEW_CLASS : GRID_CLASS)[asset.kind]?.[density]}
            />
            {hidden > 0 && index === shown.length - 1 && (
              //: 摆不下的几张:压在最后一格上说还有几张,不挡点击 —— 点开大图照样翻得到它们。
              <span
                className="pointer-events-none absolute inset-0 grid place-items-center bg-black/45 text-ui-sm font-semibold text-white"
                data-output-more=""
              >
                +{hidden}
              </span>
            )}
          </div>
        ))}
      </div>
    </figure>
  );
}

function Caption({ item, density, bleed, count = "" }: { item: AssetOutput; density: "node" | "panel"; bleed: boolean; count?: string }) {
  return (
    <figcaption className={cn("flex min-w-0 items-baseline gap-1 text-ui-2xs text-muted-foreground", bleed && "px-3 pt-1.5")}>
      <Truncate>{item.label}</Truncate>
      {count && <span className="shrink-0 tabular-nums" data-output-count="">· {count}</span>}
      {/* 检查器里名字后面跟稳定 key(和下面文字产出那几行一样):它是 `{{节点.key}}` 里要写的那个词。
          卡片上只报名字 —— 位置不够,key 在检查器里看。 */}
      {density === "panel" && item.key && item.key !== item.label && <span className="shrink-0 font-mono">{item.key}</span>}
    </figcaption>
  );
}
