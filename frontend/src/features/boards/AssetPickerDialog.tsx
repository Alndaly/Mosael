import React from "react";
import { Image as ImageIcon, LayoutGrid, SearchX, Upload } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { AssetGridPicker, AssetKindSwitch, type GridAsset } from "@/components/app/AssetGridPicker";
import { Button } from "@/components/ui/button";
import { kindIcon, kindText, MEDIA_KINDS, type MediaKind } from "@/features/boards/boardNodes";
import { placedAsset, type PlacedAsset } from "@/features/boards/boardPlacement";
import { AssetUploadStatus, acceptFor, fileKind, useAssetUpload, wrongKindText } from "@/features/boards/assetUpload";
import { useAssetDetails, useAssetSearch } from "@/lib/assetQueries";
import { useFileDrop } from "@/lib/useFileDrop";
import { cn } from "@/lib/utils";

/**
 * 往画板上贴一份现成素材:从素材库里挑(网格的样子见 AssetGridPicker,全应用挑媒体是同一个弹窗)。
 *
 * 两种挑法:
 * - **给一格换一份**(`kind` 是一种媒体):只列那一类。给视频格列图片,等于让人选一个贴上去之后是空白框的
 *   东西 —— 选择器里能选到的,就应该是贴上去能看的。
 * - **「添加 → 从库里放 → 素材」**(`kind` 是 `media`):图片、视频、音频都列,头里一组分段按种类筛;挑中哪一种
 *   就放哪一种格子(`onPick` 交回它的种类和名字,和拖进来的文件落成同样的一格,见 boardPlacement.assetFields)。
 *
 * 给了 `onBoard`(这张画板上已有的素材,时间线格的「+」)时头里多一枚「这张画板上的」,打开时先按它筛 ——
 * 往时间线里拼的多半是刚在画板上生成的那几段;点掉它就是整个素材库。
 *
 * **库里没有就直接传一个**:头里右边一颗「上传本地文件」,把文件拖到弹窗上任何地方也行(整个弹窗盖一层「松手上传」,
 * 见 assetUpload)。只收这一格要的那一种(三种都列时三种都收),传完就当是挑中了它 —— 和点一格同一个 `onPick`。
 */

/** 挑得出来的素材种类:媒体三种,画板「从库里放」时还有文档。 */
export type PickedKind = PlacedAsset["kind"];

/** 「这张画板上的」那几份按 id 取回来,没有服务端的排序:和素材库一样,最新的在前。 */
function newestFirst(a: GridAsset, b: GridAsset): number {
  return (b.created_at ?? "").localeCompare(a.created_at ?? "");
}

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
  onPick: (asset: PlacedAsset) => void;
  /** 三种都列时连文档一起列(画板「从库里放」:文档落成一格文档格)。时间线的「+」不列 —— 文档放不上时间线。 */
  withDocuments?: boolean;
  /** 这张画板上已有的素材(去重)。给了就多一枚「这张画板上的」筛选,打开时先按它筛。 */
  onBoard?: readonly string[];
}) {
  const t = useI18n();
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

  //: 整个素材库:种类和搜索词交给服务端,往下滚接着取(见 useAssetSearch)。
  const library = useAssetSearch({ workspace_id: workspaceId, kind: [...kinds] }, { enabled: open && !boardOnly });
  //: 「这张画板上的」:就是那几份,按 id 取 —— 一张画板上的素材通常就几十份,不必翻页;搜索在这几份里筛。
  const boardAssets = useAssetDetails(open && boardOnly ? [...boardSet] : []);
  const onBoardItems = React.useMemo(() => {
    const needle = library.text.trim().toLowerCase();
    return [...boardAssets.byId.values()]
      .filter(
        (asset) =>
          (kinds as readonly string[]).includes(asset.kind) &&
          (!needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle)),
      )
      .sort(newestFirst);
  }, [boardAssets.byId, kinds, library.text]);
  const items: readonly GridAsset[] = boardOnly ? onBoardItems : library.items;

  //: 直接传一个:只收这一格要的那一种;收不了的就地说一句(拖进图片槽的一段视频)。
  const upload = useAssetUpload(workspaceId);
  const chooser = React.useRef<HTMLInputElement | null>(null);
  const wanted = mixed ? "media" : kind;
  const take = (files: File[]) => {
    const file = files.find((one) => {
      const found = fileKind(one);
      return found !== null && (wanted === "media" || found === wanted);
    });
    if (!file) {
      if (files[0]) upload.reject(wrongKindText(t, files[0], wanted));
      return;
    }
    upload.start(file, (asset) => {
      const placed = placedAsset(asset);
      if (placed) onPick(placed);
    });
  };
  //: 收不了的也交给 take,由它说为什么 —— 筛掉的话松手之后什么都不发生。
  const drop = useFileDrop(take);

  const kindLabel = (one: PickedKind) => (one === "document" ? t("kindDocument") : kindText(t, one).label);
  //: 空着:搜了字、按了筛选还没有,是「没有匹配的」;什么都没筛就没有,是库里还没有这一种 —— 告诉人可以直接传。
  const narrowed = library.text.trim() !== "" || boardOnly || only !== "all";
  const EmptyIcon = mixed ? ImageIcon : kindIcon(kind);
  const empty = narrowed
    ? { icon: <SearchX />, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
    : {
        icon: <EmptyIcon />,
        title: t(mixed ? "boardsNoMedia" : kind === "video" ? "boardsNoVideos" : kind === "audio" ? "boardsNoAudios" : "boardsNoImages"),
        body: t("boardsPickEmptyHint"),
      };

  return (
    <AssetGridPicker
      open={open}
      onOpenChange={onOpenChange}
      title={t(mixed ? "boardsPickMedia" : kind === "video" ? "boardsPickVideo" : kind === "audio" ? "boardsPickAudio" : "boardsPickImage")}
      searchLabel={t("boardsSearchImages")}
      query={library.text}
      onQueryChange={library.search}
      toolbar={
        <>
          {mixed && (
            <AssetKindSwitch
              label={t("boardsPickMediaKind")}
              value={only}
              options={[{ value: "all", label: t("boardsPickMediaAll") }, ...listed.map((one) => ({ value: one, label: kindLabel(one) }))]}
              onChange={setOnly}
            />
          )}
          {/* 「这张画板上的」和按种类筛是两件事(可以叠着用):它是一枚开关,不进分段那一组。 */}
          {boardSet.size > 0 && (
            <Button
              size="sm"
              variant="outline"
              aria-pressed={boardOnly}
              data-pick-on-board=""
              className={cn(boardOnly && "border-primary/40 bg-accent text-primary hover:bg-accent hover:text-primary")}
              onClick={() => setBoardOnly((on) => !on)}
            >
              <LayoutGrid />
              {t("boardsPickOnBoard")}
            </Button>
          )}
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => chooser.current?.click()}>
            <Upload />
            {t("boardsUploadLocal")}
          </Button>
          <input
            ref={chooser}
            type="file"
            accept={acceptFor(wanted)}
            hidden
            onChange={(event) => {
              take(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
        </>
      }
      banner={<AssetUploadStatus upload={upload} />}
      dropzone={{
        handlers: drop.handlers,
        //: 盖住整个弹窗(头、网格、右上角的关闭一起,所以比它高一层):松手的地方在哪都算,不是某一个方框。
        overlay: drop.active ? (
          <div className="pointer-events-none absolute inset-0 z-30 grid rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_8%,var(--background))] p-4">
            <div className="grid place-items-center rounded-lg border-2 border-dashed border-primary/70">
              <span className="grid justify-items-center gap-2 text-center">
                <span className="grid size-12 place-items-center rounded-xl bg-accent text-primary">
                  <Upload size={22} />
                </span>
                <span className="text-ui-md font-semibold text-primary">{t("boardsUploadDropHint")}</span>
                <span className="text-ui-sm text-muted-foreground">
                  {t("boardsUploadDropKinds").replace("{kind}", t(`assetUploadKind_${wanted}` as MessageKey))}
                </span>
              </span>
            </div>
          </div>
        ) : null,
      }}
      items={items}
      onActivate={(asset) => {
        const placed = placedAsset(asset);
        if (placed) onPick(placed);
      }}
      mixedKinds={mixed}
      pending={boardOnly ? !boardAssets.settled : library.isLoading}
      error={!boardOnly && library.isError ? library.error.message : null}
      onRetry={() => void library.refetch()}
      onReachEnd={!boardOnly && library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
      loadingMore={!boardOnly && library.isFetchingNextPage}
      empty={empty}
    />
  );
}
