import React from "react";
import { useQuery } from "@tanstack/react-query";

import { API_BASE, listAssets, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * 往画板上贴一张图:从素材库里挑。
 *
 * **只列图片。** 画板上的 image 项渲染的是 `<img>`,把视频/音频列出来等于让人选一个贴上去
 * 之后是空白框的东西 —— 选择器里能选到的,就应该是贴上去能看的。
 */
export function AssetPickerDialog({
  open,
  workspaceId,
  onOpenChange,
  onPick,
}: {
  open: boolean;
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
    const all = (assets.data ?? []).filter((asset: Asset) => asset.kind === "image");
    const needle = keyword.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((asset: Asset) =>
      `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
    );
  }, [assets.data, keyword]);

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("boardsPickImage")} className="w-[560px]">
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
          <p className="py-8 text-center text-ui-xs text-muted-foreground">{t("boardsNoImages")}</p>
        ) : (
          <div className="grid max-h-[380px] grid-cols-4 gap-2 overflow-y-auto">
            {images.map((asset: Asset) => (
              <button
                key={asset.id}
                type="button"
                onClick={() => onPick(asset.id)}
                title={asset.name || asset.original_filename || ""}
                className="group aspect-square cursor-pointer overflow-hidden rounded-md border border-border transition-colors hover:border-primary"
              >
                <img
                  src={`${API_BASE}/api/assets/${asset.id}/file`}
                  alt={asset.name || ""}
                  loading="lazy"
                  className="h-full w-full object-cover"
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </ModalShell>
  );
}
