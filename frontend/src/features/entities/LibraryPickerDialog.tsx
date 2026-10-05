import React from "react";
import { Check, Film, ImageIcon, Search } from "lucide-react";

import { assetThumbnailUrl, type AssetCard } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { assetGallery, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { ViewFullSizeButton } from "@/components/app/view-full-size";
import { Truncate } from "@/components/ui/truncate";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAssetSearch } from "@/lib/assetQueries";
import { useReachEnd } from "@/lib/useReachEnd";
import { cn } from "@/lib/utils";

type KindFilter = "all" | "image" | "video";
const KIND_FILTERS: readonly KindFilter[] = ["all", "image", "video"];
const GRID = "grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-3";

/**
 * 「从素材库添加」:在弹窗里挑参考图 —— 搜名字、按图片 / 视频筛、点着多选,一次挂好几张。
 * 已经挂在这个资产上的照样列出来,标着「已挂上」、不能再选,免得人以为素材库里没有它。
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

  const items = assets.items;
  const end = useReachEnd<HTMLLIElement>(
    assets.hasNextPage ? () => void (assets.isFetchingNextPage || assets.fetchNextPage()) : undefined,
    items.length,
  );
  const toggle = (id: string) => setPicked((current) => (current.includes(id) ? current.filter((one) => one !== id) : [...current, id]));
  //: 点格子是勾选;看大图走格子角上那颗,左右翻的是眼下筛出来的这一屏(搜索词、图片 / 视频)。
  const { openImagePreview } = useImagePreview();
  const gallery = React.useMemo(() => assetGallery(items), [items]);
  const preview = (asset: AssetCard) => {
    const item = assetPreviewItem(asset);
    if (item) openImagePreview({ ...item, gallery });
  };
  const filterLabel: Record<KindFilter, string> = { all: t("entityLibraryAll"), image: t("entityLibraryImages"), video: t("entityLibraryVideos") };

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={t("entityFromLibrary")}
      className="w-[min(920px,calc(100vw-48px))] h-[min(720px,calc(100dvh-48px))]"
      header={
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="relative min-w-48 flex-1">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              size="sm"
              className="pl-8"
              aria-label={t("entityLibrarySearch")}
              placeholder={t("entityLibrarySearch")}
              value={assets.text}
              onChange={(event) => search(event.currentTarget.value)}
            />
          </span>
          <div role="radiogroup" aria-label={t("entityLibraryKind")} className="flex gap-1">
            {KIND_FILTERS.map((one) => (
              <button
                key={one}
                type="button"
                role="radio"
                aria-checked={kind === one}
                onClick={() => setKind(one)}
                className={cn(
                  "cursor-pointer rounded-full border-0 px-2.5 py-1 text-ui-xs transition-colors",
                  kind === one ? "bg-action text-action-foreground" : "bg-secondary text-muted-foreground hover:text-foreground",
                )}
              >
                {filterLabel[one]}
              </button>
            ))}
          </div>
        </div>
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
    >
      {assets.isPending ? (
        <div className={GRID} aria-busy="true">
          {Array.from({ length: 12 }, (_, index) => (
            <Skeleton key={index} className="aspect-square w-full rounded-lg" />
          ))}
        </div>
      ) : assets.isError ? (
        <div role="alert" className="grid justify-items-center gap-3 py-16 text-center text-ui-sm text-muted-foreground">
          {assets.error.message}
          <Button variant="outline" size="sm" onClick={() => void assets.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : items.length === 0 ? (
        <div className="grid justify-items-center gap-2 py-16 text-center text-ui-sm text-muted-foreground">
          <ImageIcon size={26} strokeWidth={1.3} />
          {assets.query || kind !== "all" ? t("studioNoMatches") : t("entityLibraryEmpty")}
        </div>
      ) : (
        <ul className={cn("m-0 list-none p-0", GRID)} role="listbox" aria-multiselectable="true" aria-label={t("entityLibraryTitle")}>
          {items.map((asset) => (
            <Tile
              key={asset.id}
              asset={asset}
              attached={attached.has(asset.id)}
              order={picked.indexOf(asset.id)}
              onToggle={() => toggle(asset.id)}
              onPreview={() => preview(asset)}
            />
          ))}
          {/* 末尾一条线:进了视野就接着取下一页。占满一整行,不挤进格子里。 */}
          {assets.hasNextPage && <li ref={end} aria-hidden="true" className="col-span-full h-px" />}
        </ul>
      )}
    </ModalShell>
  );
}

/** 一格素材。选中时右上角是挑的先后(1、2、3 —— 挂上去就是这个顺序)。 */
function Tile({ asset, attached, order, onToggle, onPreview }: { asset: AssetCard; attached: boolean; order: number; onToggle: () => void; onPreview: () => void }) {
  const t = useI18n();
  const selected = order >= 0;
  const name = asset.name || asset.original_filename || "";
  return (
    <li className="grid min-w-0 gap-1.5">
      <div className="group/preview relative">
        <button
          type="button"
          role="option"
          aria-selected={selected}
          aria-disabled={attached || undefined}
          aria-label={name}
          disabled={attached}
          onClick={onToggle}
          data-library-asset={asset.id}
          className={cn(
            "relative grid aspect-square w-full cursor-pointer place-items-center overflow-hidden rounded-lg border bg-panel-inset p-0 text-muted-foreground transition-[border-color,box-shadow]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
            selected ? "border-primary ring-2 ring-primary" : "border-border hover:border-border-strong",
          )}
        >
          {asset.kind === "image" ? (
            <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className={cn("absolute inset-0 size-full object-cover", attached && "opacity-40")} />
          ) : (
            <Film size={22} strokeWidth={1.4} />
          )}
          {selected && (
            <span className="absolute right-1.5 top-1.5 grid size-5 place-items-center rounded-full bg-action text-ui-2xs font-semibold text-action-foreground">
              {order + 1}
            </span>
          )}
          {attached && (
            <span className="absolute inset-x-1.5 bottom-1.5 inline-flex items-center justify-center gap-1 rounded-md bg-background/85 py-0.5 text-ui-2xs text-foreground backdrop-blur">
              <Check size={11} />
              {t("entityLibraryAttached")}
            </span>
          )}
        </button>
        {/* 已经挂上的那张也能看大图 —— 不能再选,不等于不能看。 */}
        <ViewFullSizeButton name={name} onOpen={onPreview} className="left-1.5 top-1.5" />
      </div>
      <Truncate className="px-0.5 text-ui-xs text-muted-foreground">
        {name}
      </Truncate>
    </li>
  );
}
