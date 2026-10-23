import React from "react";
import { ChevronDown, Video } from "lucide-react";

import { useAssetSearch } from "@/lib/assetQueries";
import { useI18n } from "@/app/preferences";
import { AssetGridPicker, type GridAsset } from "@/components/app/AssetGridPicker";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 发布页的「成片素材」——**点开弹窗挑一份**。
 *
 * 此前是一个就地展开的下拉(几十份素材的名字排成一列,滚起来像日志;和「从素材库里挑素材」这件事在
 * 应用里别处长的样子也不一样)。应用里挑媒体只有一种样子:那个**缩略图当主角的弹窗**
 * (见 `components/app/AssetGridPicker`,画板、参考图、换素材都用它)。
 *
 * 所以这里只做一件事:一个长得像输入框的触发器(显示当前成片名)+ 那个共用弹窗,单选,
 * 点一格就选中并关窗。素材库的筛选、搜索、翻页、上传都在弹窗里(和画板挑素材同一套)。
 */
export function AssetPickerField({
  workspaceId,
  value,
  label,
  placeholder,
  onChange,
}: {
  workspaceId: string;
  /** 选中的素材 id(空 = 还没挑)。 */
  value: string;
  /** 当前成片的名字(调用方已经知道,不必为本字段再查一次)。 */
  label: string;
  placeholder: string;
  onChange: (assetId: string, name: string) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  //: 只列视频:这一格收的就是成片。
  const library = useAssetSearch(
    { workspace_id: workspaceId, kind: ["video"] },
    { enabled: open },
  );

  const pick = (asset: GridAsset) => {
    onChange(asset.id, asset.name || asset.original_filename || t("publishAssetFallbackName"));
    setOpen(false);
  };

  return (
    <>
      {/*: 触发器用共用的 Button(不手写 `<button>`,见 design/nativeButtons):外形仍是「一个字段」——
          和旁边的输入框同高同描边,右边一枚箭头;它点开的是一整个挑素材的弹窗。 */}
      <Button
        variant="outline"
        //: Button 的默认档就是 40px(和字段同高),不必再写 size。
        className="w-full justify-between font-normal"
        data-asset-picker=""
        aria-label={placeholder}
        onClick={() => setOpen(true)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Video size={14} className="shrink-0 text-muted-foreground" />
          <Truncate className={cn("min-w-0", !value && "text-muted-foreground")}>{value ? label : placeholder}</Truncate>
        </span>
        <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
      </Button>
      {/*: 弹窗**开着才挂**:`AssetGridPicker` 要用图片预览的上下文(它自己那层 Provider 在弹窗里),
          常挂着会在没有预览 Provider 的地方渲染 —— 单测里就是一句 "useImagePreview must be used inside"。 */}
      {open && (
      <AssetGridPicker
        open={open}
        onOpenChange={setOpen}
        title={t("publishPickVideoTitle")}
        description={t("publishPickVideoDesc")}
        searchLabel={t("searchAssets")}
        query={library.text}
        onQueryChange={library.search}
        items={library.items}
        onActivate={pick}
        pending={library.isLoading}
        error={library.isError ? library.error.message : null}
        onRetry={() => void library.refetch()}
        onReachEnd={library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
        loadingMore={library.isFetchingNextPage}
        empty={
          library.text.trim()
            ? { icon: <Video />, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
            : { icon: <Video />, title: t("publishNoVideos"), body: t("publishPickVideoDesc") }
        }
        footer={
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            {t("close")}
          </Button>
        }
      />
      )}
    </>
  );
}
