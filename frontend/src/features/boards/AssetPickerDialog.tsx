import React from "react";
import { Music } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { assetThumbnailUrl, listAssets, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";
import type { MediaKind } from "@/features/boards/boardNodes";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * 往画板上贴一张图:从素材库里挑。
 *
 * **只列图片。** 画板上的 image 项渲染的是 `<img>`,把视频/音频列出来等于让人选一个贴上去
 * 之后是空白框的东西 —— 选择器里能选到的,就应该是贴上去能看的。
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
    queryKey: ["assets", workspaceId],
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

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t(kind === "video" ? "boardsPickVideo" : kind === "audio" ? "boardsPickAudio" : "boardsPickImage")} className="w-[560px]">
      <div className="grid gap-2">
        <Input
          autoFocus
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder={t("boardsSearchImages")}
          className="h-8"
        />
        {assets.isLoading ? (
          <div className="grid grid-cols-4 gap-2">
            {[0, 1, 2, 3].map((n) => (
              <Skeleton key={n} className="aspect-square rounded-md" />
            ))}
          </div>
        ) : images.length === 0 ? (
          <p className="py-8 text-center text-ui-xs text-muted-foreground">{t(kind === "video" ? "boardsNoVideos" : kind === "audio" ? "boardsNoAudios" : "boardsNoImages")}</p>
        ) : (
          // **一行一个,不是缩略图墙。** 光看图分不出「同一个人的三版」哪个是哪个 ——
          // 名字、尺寸、时长才是真正用来挑的信息。缩略图退到行首当认脸用。
          //
          // 顺带修掉一个布局错:此前是 grid-cols-4 + aspect-square,而 grid 默认 align-items:
          // stretch —— 一行里最高的那个把整行撑开,其余的图就顶破了自己的格子。
          <div className="grid max-h-[380px] content-start gap-1 overflow-y-auto">
            {images.map((asset: Asset) => (
              <button
                key={asset.id}
                type="button"
                onClick={() => onPick(asset.id)}
                className="flex cursor-pointer items-center gap-2.5 rounded-md border border-transparent p-1.5 text-left transition-colors hover:border-border hover:bg-secondary"
              >
                {/* 音频没有缩略图 —— 拿它的 URL 去当图片只会得到一个碎图标。 */}
                {kind === "audio" ? (
                  <span className="grid h-10 w-14 shrink-0 place-items-center rounded bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] text-muted-foreground">
                    <Music size={16} />
                  </span>
                ) : (
                  <img
                    src={assetThumbnailUrl(asset.id)}
                    alt=""
                    loading="lazy"
                    className="h-10 w-14 shrink-0 rounded bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] object-cover"
                  />
                )}
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate text-ui-xs text-foreground">
                    {asset.name || asset.original_filename}
                  </span>
                  <span className="truncate text-ui-2xs text-muted-foreground">{describe(asset)}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </ModalShell>
  );
}
