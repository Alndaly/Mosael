import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { Image as ImageIcon, Music } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { assetThumbnailUrl, listAssets, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { Button } from "@/components/ui/button";
import { kindIcon, kindText, MEDIA_KINDS, type MediaKind } from "@/features/boards/boardNodes";

/**
 * 往画板上贴一份现成素材:从素材库里挑。
 *
 * 两种挑法:
 * - **给一格换一份**(`kind` 是一种媒体):只列那一类。给视频格列图片,等于让人选一个贴上去之后是空白框的
 *   东西 —— 选择器里能选到的,就应该是贴上去能看的。
 * - **「添加 → 从库里放 → 素材」**(`kind` 是 `media`):图片、视频、音频都列,头里一排按种类筛;挑中哪一种
 *   就放哪一种格子(`onPick` 交回它的种类)。此前「添加」里是图片、视频、音频三行,和「新建」那三行是同样的格子。
 *
 * 给了 `onBoard`(这张画板上已有的素材,时间线格的「+」)时头里多一枚「这张画板上的」,打开时先按它筛 ——
 * 往时间线里拼的多半是刚在画板上生成的那几段;点掉它就是整个素材库。
 */
/** 行尾那句说明:尺寸、时长 —— 挑素材时真正要看的东西。取不到就不写,不编。 */
function describe(asset: Asset): string {
  const info = (asset.media_info ?? {}) as { width?: number; height?: number; duration?: number };
  const parts: string[] = [];
  if (info.width && info.height) parts.push(`${info.width}×${info.height}`);
  if (info.duration) parts.push(`${Math.round(info.duration)}s`);
  return parts.join(" · ");
}

/** 挑得出来的素材种类:媒体三种,画板「从库里放」时还有文档。 */
export type PickedKind = MediaKind | "document";

export function AssetPickerDialog({
  open,
  kind,
  workspaceId,
  onOpenChange,
  onPick,
  onBoard,
  withDocuments = false,
}: {
  open: boolean;
  /** 列哪一类;`media` 是三种都列、头里按种类筛。**选得到的就该是贴上去能看的**。 */
  kind: MediaKind | "media";
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (assetId: string, kind: PickedKind) => void;
  /** 三种都列时连文档一起列(画板「从库里放」:文档落成一格文档格)。时间线的「+」不列 —— 文档放不上时间线。 */
  withDocuments?: boolean;
  /** 这张画板上已有的素材(去重)。给了就多一枚「这张画板上的」筛选,打开时先按它筛。 */
  onBoard?: readonly string[];
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");
  const [only, setOnly] = React.useState<PickedKind | "all">("all");
  const listed: readonly PickedKind[] = withDocuments ? [...MEDIA_KINDS, "document"] : MEDIA_KINDS;
  const boardSet = React.useMemo(() => new Set(onBoard ?? []), [onBoard]);
  const [boardOnly, setBoardOnly] = React.useState(false);
  //: 每次打开:有画板上的素材就先按它筛。
  React.useEffect(() => {
    if (open) setBoardOnly(boardSet.size > 0);
  }, [open, boardSet]);
  const mixed = kind === "media";
  const kinds: readonly PickedKind[] = !mixed ? [kind] : only === "all" ? listed : [only];

  const assets = useQuery({
    queryKey: assetKeys.list(workspaceId),
    queryFn: () => listAssets(workspaceId),
    enabled: open,
  });

  const images = React.useMemo(() => {
    const all = (assets.data ?? []).filter((asset: Asset) =>
      (kinds as readonly string[]).includes(asset.kind) && (!boardOnly || boardSet.has(asset.id)));
    const needle = keyword.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((asset: Asset) =>
      `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
    );
  }, [assets.data, kinds, keyword, boardOnly, boardSet]);

  const EmptyIcon = mixed ? ImageIcon : kindIcon(kind);
  const kindLabel = (one: string) => (one === "document" ? t("kindDocument") : kindText(t, one as MediaKind).label);
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(mixed ? "boardsPickMedia" : kind === "video" ? "boardsPickVideo" : kind === "audio" ? "boardsPickAudio" : "boardsPickImage")}
      filters={
        mixed ? (
          <div role="group" aria-label={t("boardsPickMediaKind")} className="flex flex-wrap gap-1">
            {boardSet.size > 0 && (
              <Button
                type="button"
                size="sm"
                variant={boardOnly ? "secondary" : "ghost"}
                aria-pressed={boardOnly}
                data-pick-on-board=""
                onClick={() => setBoardOnly((on) => !on)}
              >
                {t("boardsPickOnBoard")}
              </Button>
            )}
            {/* 「这张画板上的」和按种类筛是两件事(可以叠着用):隔一道线,两个按下态不像同一组里的二选一。 */}
            {boardSet.size > 0 && <span aria-hidden="true" className="mx-1 my-1 w-px self-stretch bg-border" />}
            {(["all", ...listed] as const).map((one) => (
              <Button
                key={one}
                type="button"
                size="sm"
                variant={only === one ? "secondary" : "ghost"}
                aria-pressed={only === one}
                onClick={() => setOnly(one)}
              >
                {one === "all" ? t("boardsPickMediaAll") : kindLabel(one)}
              </Button>
            ))}
          </div>
        ) : undefined
      }
      searchLabel={t("boardsSearchImages")}
      query={keyword}
      onQueryChange={setKeyword}
      items={images}
      itemKey={(asset) => asset.id}
      //: **一行一个,不是缩略图墙。** 光看图分不出「同一个人的三版」哪个是哪个 —— 名字、尺寸、时长才是
      //: 真正用来挑的信息,缩略图退到行首当认脸用。音频没有缩略图:拿它的 URL 当图只会是一个碎图标。
      row={(asset) => ({
        lead:
          asset.kind === "audio" ? (
            <Music size={16} />
          ) : (
            <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
          ),
        title: asset.name || asset.original_filename || "",
        //: 三种混着列时写明是哪一种 —— 同名的一张图和一段视频,光看名字分不出。
        subtitle: [mixed ? kindLabel(asset.kind) : "", describe(asset)].filter(Boolean).join(" · "),
      })}
      onPick={(asset) => onPick(asset.id, asset.kind as PickedKind)}
      pending={assets.isLoading}
      error={assets.isError ? assets.error.message : null}
      onRetry={() => void assets.refetch()}
      empty={{
        icon: <EmptyIcon size={24} strokeWidth={1.5} />,
        text: t(mixed ? "boardsNoMedia" : kind === "video" ? "boardsNoVideos" : kind === "audio" ? "boardsNoAudios" : "boardsNoImages"),
      }}
    />
  );
}
