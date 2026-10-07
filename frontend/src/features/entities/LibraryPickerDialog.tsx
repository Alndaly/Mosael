import React from "react";
import { ImageIcon, SearchX } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { AssetGridPicker, AssetKindSwitch } from "@/components/app/AssetGridPicker";
import { Button } from "@/components/ui/button";
import { useAssetSearch } from "@/lib/assetQueries";

type KindFilter = "all" | "image" | "video";
const KIND_FILTERS: readonly KindFilter[] = ["all", "image", "video"];

/**
 * 「从素材库添加」:在弹窗里挑参考图 —— 搜名字、按图片 / 视频筛、点着多选,一次挂好几张(网格的样子见 AssetGridPicker,
 * 全应用挑媒体是同一个弹窗)。选中的格子角上是挑的先后(1、2、3 —— 挂上去就是这个顺序)。
 * 已经挂在这个资产上的照样列出来,标着「已挂上」、点不动,免得人以为素材库里没有它。
 */
export function LibraryPickerDialog({
  open,
  onOpenChange,
  workspaceId,
  attached,
  pending,
  onAdd,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  attached: ReadonlySet<string>;
  pending: boolean;
  onAdd: (assetIds: string[]) => void;
}) {
  const t = useI18n();
  const [kind, setKind] = React.useState<KindFilter>("all");
  const [picked, setPicked] = React.useState<string[]>([]);
  //: 种类和搜索词交给服务端,往下滚接着取(见 useAssetSearch)。能当参考图的只有图片和视频。
  const assets = useAssetSearch({ workspace_id: workspaceId, kind: kind === "all" ? ["image", "video"] : [kind] }, { enabled: open });
  const { search } = assets;

  React.useEffect(() => {
    if (!open) return;
    search("");
    setKind("all");
    setPicked([]);
  }, [open, search]);

  const toggle = (id: string) => setPicked((current) => (current.includes(id) ? current.filter((one) => one !== id) : [...current, id]));
  const filterLabel: Record<KindFilter, string> = { all: t("entityLibraryAll"), image: t("entityLibraryImages"), video: t("entityLibraryVideos") };
  const narrowed = assets.text.trim() !== "" || kind !== "all";

  return (
    <AssetGridPicker
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={t("entityFromLibrary")}
      searchLabel={t("entityLibrarySearch")}
      query={assets.text}
      onQueryChange={search}
      toolbar={
        <AssetKindSwitch
          label={t("entityLibraryKind")}
          value={kind}
          options={KIND_FILTERS.map((one) => ({ value: one, label: filterLabel[one] }))}
          onChange={setKind}
        />
      }
      items={assets.items}
      onActivate={(asset) => toggle(asset.id)}
      selection={{ isSelected: (asset) => picked.includes(asset.id), order: (asset) => picked.indexOf(asset.id), multiple: true }}
      taken={(asset) => (attached.has(asset.id) ? t("entityLibraryAttached") : null)}
      mixedKinds={kind === "all"}
      pending={assets.isPending}
      error={assets.isError ? assets.error.message : null}
      onRetry={() => void assets.refetch()}
      onReachEnd={assets.hasNextPage ? () => void (assets.isFetchingNextPage || assets.fetchNextPage()) : undefined}
      loadingMore={assets.isFetchingNextPage}
      empty={
        narrowed
          ? { icon: <SearchX />, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
          : { icon: <ImageIcon />, title: t("entityLibraryEmpty") }
      }
      footer={
        <>
          <span className="mr-auto text-ui-sm text-muted-foreground" data-picked-count="">
            {picked.length ? t("entityLibraryPicked").replace("{n}", String(picked.length)) : t("entityLibraryPickHint")}
          </span>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={!picked.length} loading={pending} onClick={() => onAdd(picked)}>
            {picked.length ? t("entityLibraryAdd").replace("{n}", String(picked.length)) : t("entityLibraryAttach")}
          </Button>
        </>
      }
    />
  );
}
