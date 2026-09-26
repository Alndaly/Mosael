import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { Music } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { assetThumbnailUrl, listAssets, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { kindIcon, type MediaKind } from "@/features/boards/boardNodes";

/**
 * 往画板上贴一份现成素材:从素材库里挑。
 *
 * **一次只列一类**(由 `kind` 决定)。给视频节点列图片,等于让人选一个贴上去之后是空白框的
 * 东西 —— 选择器里能选到的,就应该是贴上去能看的。
 */
/** 行尾那句说明:尺寸、时长 —— 挑素材时真正要看的东西。取不到就不写,不编。 */
function describe(asset: Asset): string {
  const info = (asset.media_info ?? {}) as { width?: number; height?: number; duration?: number };
  const parts: string[] = [];
  if (info.width && info.height) parts.push(`${info.width}×${info.height}`);
  if (info.duration) parts.push(`${Math.round(info.duration)}s`);
  return parts.join(" · ");
}

export function AssetPickerDialog({
  open,
  kind,
  workspaceId,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  /** 列哪一类。**选得到的就该是贴上去能看的** —— 给视频节点列图片等于让人选一个放不了的东西。 */
  kind: MediaKind;
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (assetId: string) => void;
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");

  const assets = useQuery({
    queryKey: assetKeys.list(workspaceId),
    queryFn: () => listAssets(workspaceId),
    enabled: open,
  });

  const images = React.useMemo(() => {
    const all = (assets.data ?? []).filter((asset: Asset) => asset.kind === kind);
    const needle = keyword.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((asset: Asset) =>
      `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
    );
  }, [assets.data, kind, keyword]);

  const EmptyIcon = kindIcon(kind);
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(kind === "video" ? "boardsPickVideo" : kind === "audio" ? "boardsPickAudio" : "boardsPickImage")}
      searchLabel={t("boardsSearchImages")}
      query={keyword}
      onQueryChange={setKeyword}
      items={images}
      itemKey={(asset) => asset.id}
      //: **一行一个,不是缩略图墙。** 光看图分不出「同一个人的三版」哪个是哪个 —— 名字、尺寸、时长才是
      //: 真正用来挑的信息,缩略图退到行首当认脸用。音频没有缩略图:拿它的 URL 当图只会是一个碎图标。
      row={(asset) => ({
        lead:
          kind === "audio" ? (
            <Music size={16} />
          ) : (
            <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
          ),
        title: asset.name || asset.original_filename || "",
        subtitle: describe(asset),
      })}
      onPick={(asset) => onPick(asset.id)}
      pending={assets.isLoading}
      error={assets.isError ? assets.error.message : null}
      onRetry={() => void assets.refetch()}
      empty={{
        icon: <EmptyIcon size={24} strokeWidth={1.5} />,
        text: t(kind === "video" ? "boardsNoVideos" : kind === "audio" ? "boardsNoAudios" : "boardsNoImages"),
      }}
    />
  );
}
