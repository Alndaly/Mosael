import React from "react";
import { FileUp, Image as ImageIcon, Music, Upload } from "lucide-react";

import { assetThumbnailUrl, type AssetCard } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { assetGallery, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { PickListDialog } from "@/components/app/PickListDialog";
import { Button } from "@/components/ui/button";
import { kindIcon, kindText, MEDIA_KINDS, type MediaKind } from "@/features/boards/boardNodes";
import { placedAsset, type PlacedAsset } from "@/features/boards/boardPlacement";
import { AssetUploadStatus, acceptFor, fileKind, useAssetUpload, wrongKindText } from "@/features/boards/assetUpload";
import { useAssetDetails, useAssetSearch } from "@/lib/assetQueries";
import { useFileDrop } from "@/lib/useFileDrop";

/**
 * 往画板上贴一份现成素材:从素材库里挑。
 *
 * 两种挑法:
 * - **给一格换一份**(`kind` 是一种媒体):只列那一类。给视频格列图片,等于让人选一个贴上去之后是空白框的
 *   东西 —— 选择器里能选到的,就应该是贴上去能看的。
 * - **「添加 → 从库里放 → 素材」**(`kind` 是 `media`):图片、视频、音频都列,头里一排按种类筛;挑中哪一种
 *   就放哪一种格子(`onPick` 交回它的种类和名字,和拖进来的文件落成同样的一格,见 boardPlacement.assetFields)。此前「添加」里是图片、视频、音频三行,和「新建」那三行是同样的格子。
 *
 * 给了 `onBoard`(这张画板上已有的素材,时间线格的「+」)时头里多一枚「这张画板上的」,打开时先按它筛 ——
 * 往时间线里拼的多半是刚在画板上生成的那几段;点掉它就是整个素材库。
 *
 * **库里没有就直接传一个**:头里一枚「上传本地文件」,把文件拖进弹窗也行(见 assetUpload)。只收这一格要的那一种
 * (三种都列时三种都收),传完就当是挑中了它 —— 和点一行同一个 `onPick`。
 */
/** 行尾那句说明:尺寸、时长 —— 挑素材时真正要看的东西。取不到就不写,不编。 */
/** 清单里的一行:素材库的卡片,或「这张画板上的」那几份的详情 —— 两种都有这几样。 */
type PickerRow = Pick<AssetCard, "id" | "name" | "original_filename" | "kind"> & { media_info: Record<string, unknown> };

function describe(asset: PickerRow): string {
  const info = asset.media_info as { width?: number | null; height?: number | null; duration?: number | null };
  const parts: string[] = [];
  if (info.width && info.height) parts.push(`${info.width}×${info.height}`);
  if (info.duration) parts.push(`${Math.round(info.duration)}s`);
  return parts.join(" · ");
}

/** 挑得出来的素材种类:媒体三种,画板「从库里放」时还有文档。 */
export type PickedKind = PlacedAsset["kind"];

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
    return [...boardAssets.byId.values()].filter(
      (asset) =>
        (kinds as readonly string[]).includes(asset.kind) &&
        (!needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [boardAssets.byId, kinds, library.text]);
  const images: readonly PickerRow[] = boardOnly ? onBoardItems : library.items;
  //: 点一行是挑;看大图走行首缩略图上那颗,左右翻的是眼下这份清单里的图和视频(同样的筛选、同样的搜索词)。
  const { openImagePreview } = useImagePreview();
  const gallery = React.useMemo(() => assetGallery(images), [images]);
  const previewOf = (asset: PickerRow) => {
    const item = assetPreviewItem(asset);
    return item ? () => openImagePreview({ ...item, gallery }) : undefined;
  };

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
      actions={
        <div className="grid gap-1.5">
          <div className="flex items-center gap-1">
            <Button type="button" size="sm" variant="ghost" className="gap-1.5" onClick={() => chooser.current?.click()}>
              <Upload size={14} />
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
          </div>
          <AssetUploadStatus upload={upload} />
        </div>
      }
      dropzone={{
        handlers: drop.handlers,
        overlay: drop.active ? (
          <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
            <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
              <FileUp size={20} />
              {t("boardsUploadDropHint")}
            </span>
          </div>
        ) : null,
      }}
      searchLabel={t("boardsSearchImages")}
      query={library.text}
      onQueryChange={library.search}
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
        preview: previewOf(asset),
      })}
      onPick={(asset) => {
        const placed = placedAsset(asset);
        if (placed) onPick(placed);
      }}
      pending={boardOnly ? !boardAssets.settled : library.isLoading}
      error={!boardOnly && library.isError ? library.error.message : null}
      onRetry={() => void library.refetch()}
      onReachEnd={!boardOnly && library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
      loadingMore={!boardOnly && library.isFetchingNextPage}
      empty={{
        icon: <EmptyIcon size={24} strokeWidth={1.5} />,
        text: t(mixed ? "boardsNoMedia" : kind === "video" ? "boardsNoVideos" : kind === "audio" ? "boardsNoAudios" : "boardsNoImages"),
      }}
    />
  );
}
