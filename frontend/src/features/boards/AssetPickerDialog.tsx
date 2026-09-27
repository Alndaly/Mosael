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
  /** 列哪一类;`media` 是三种都列、头里按种类筛。**选得到的就该是贴上去能看的**。 */
  kind: MediaKind | "media";
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (assetId: string, kind: MediaKind) => void;
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");
  const [only, setOnly] = React.useState<MediaKind | "all">("all");
  const mixed = kind === "media";
  const kinds: readonly MediaKind[] = !mixed ? [kind] : only === "all" ? MEDIA_KINDS : [only];

  const assets = useQuery({
    queryKey: assetKeys.list(workspaceId),
    queryFn: () => listAssets(workspaceId),
    enabled: open,
  });

  const images = React.useMemo(() => {
    const all = (assets.data ?? []).filter((asset: Asset) => (kinds as readonly string[]).includes(asset.kind));
    const needle = keyword.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((asset: Asset) =>
      `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
    );
  }, [assets.data, kinds, keyword]);

  const EmptyIcon = mixed ? ImageIcon : kindIcon(kind);
  const kindLabel = (one: string) => kindText(t, one as MediaKind).label;
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(mixed ? "boardsPickMedia" : kind === "video" ? "boardsPickVideo" : kind === "audio" ? "boardsPickAudio" : "boardsPickImage")}
      filters={
        mixed ? (
          <div role="group" aria-label={t("boardsPickMediaKind")} className="flex flex-wrap gap-1">
            {(["all", ...MEDIA_KINDS] as const).map((one) => (
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
      onPick={(asset) => onPick(asset.id, asset.kind as MediaKind)}
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
