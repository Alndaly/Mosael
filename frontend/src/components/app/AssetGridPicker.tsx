import React from "react";
import { Check, FileText, Image as ImageIcon, Loader2, Play, Video } from "lucide-react";

import { assetThumbnailUrl, type AssetCard } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { assetGallery, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { ModalShell } from "@/components/app/modals";
import { ViewFullSizeButton } from "@/components/app/view-full-size";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import { Truncate } from "@/components/ui/truncate";
import { assetKindKey, documentFacts, kindIsVisual } from "@/lib/assetKinds";
import { assetOriginKey } from "@/lib/assetOrigin";
import { formatTimecode, parseServerTime, relativeTime } from "@/lib/time";
import { useElementWidth } from "@/lib/useElementWidth";
import { useVirtualRows } from "@/lib/useVirtualRows";
import { cn } from "@/lib/utils";

/**
 * 「从素材库里挑一份」的弹窗:**全应用挑媒体只有这一种样子** —— 画板上挑素材(AssetPickerDialog)、给资产挂参考图
 * (LibraryPickerDialog)、给片段换素材(ReplaceMediaDialog)。挑笔记、挑 3D 场景这种「按名字挑」的清单是 PickListDialog。
 *
 * 此前挑素材是一行一个、行首 36px 的小缩略图(维护者:「这个弹窗 UI 太丑了」)。可挑媒体的人是**看着挑**的:
 *
 * - **一格一份,缩略图是主角**:4:3 的格子,图片和视频完整放进去(`object-contain`,竖图不被裁成一条);视频右下角是时长;
 *   音频画一条按 id 定形的波形;文档是第一页的缩略图,没有就是图标和格式。
 * - **格子下面三行**:名字(截断,悬停看全名)、种类和尺寸(文档是格式、页数、大小)、来源和多久以前加的(悬停看具体时间)。
 *   同名的四张「Generation · girl.json」靠后两行分得开 —— 哪张是三分钟前 AI 生成的,哪张是昨天导入的。顺序是服务端给的,
 *   最新的在前。
 * - **头钉在上面**:标题、搜索、调用方给的筛选和动作(`toolbar`),再下面一条(`banner`:上传进度、「一起换」的开关);
 *   只有网格在滚。网格只画看得见的那几行(见 useVirtualRows,和素材库同一套),滚到底附近就要下一页(`onReachEnd`)。
 * - **键盘挑得完**:打开就在搜索框里,回车挑高亮的那一格;↓ 进网格,方向键在格子间走,回车挑,在第一行按 ↑ 回到搜索框;
 *   Esc 关窗。鼠标悬停和键盘走到的是同一种高亮。
 * - **看大图不抢点击**:点一格是挑;图和视频的格子左上角有一颗「看大图」(悬停或键盘走到这一格时露出来),
 *   左右翻的是眼下这份网格里的图和视频。
 *
 * 点一格做什么由调用方定(`onActivate`):画板上点了就挑中、弹窗关掉;要多选或先选再确认的给 `selection`,
 * 选中的格子描主色、角上标先后或一个勾,确认的按钮放在 `footer`。已经用上的(挂过的参考图)给 `taken`:照样列出来,
 * 免得人以为素材库里没有它,但标一句、点不动。
 *
 * 加载中是和格子同样大小的骨架;读不出来、一份都没有、筛完没有由这里画,说法由调用方给(`empty`)。
 */

/** 一格要用到的素材字段:素材库的卡片有,按 id 取来的详情也有。 */
export type GridAsset = Pick<
  AssetCard,
  "id" | "kind" | "name" | "original_filename" | "source" | "derived" | "ai_generated" | "created_at"
> & { media_info: Record<string, unknown> };

/** 一格至少这么宽(含格子自己的内边距),一行能放几格就放几格。 */
const TILE_MIN_PX = 172;
/** 格子之间的缝(gap-x-1 / 每行的 pb-1)。格子自己还有 8px 内边距,缩略图之间看着是 20px。 */
const GRID_GAP_PX = 4;
/** 格子的内边距(p-2):悬停、高亮的底色比缩略图大一圈。 */
const TILE_PAD_PX = 8;
/** 缩略图下面那三行字连同上面的缝大约多高;画出来之后按量到的算,这只是还没画时的估计。 */
const TILE_TEXT_PX = 66;
/** 已经画到倒数第几行时去要下一页:人滚到底之前,下一页已经到了。 */
const PREFETCH_ROWS = 3;

export function AssetGridPicker<T extends GridAsset>({
  open,
  onOpenChange,
  title,
  description,
  searchLabel,
  query,
  onQueryChange,
  toolbar,
  banner,
  items,
  onActivate,
  selection,
  taken,
  mixedKinds = false,
  pending = false,
  error = null,
  onRetry,
  empty,
  onReachEnd,
  loadingMore = false,
  dropzone,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 标题下面一句:挑了之后会怎样(「位置、时长都不动,只换素材」)。 */
  description?: string;
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  /** 搜索框同一行、靠右的筛选和动作(按种类筛、「这张画板上的」、上传)。 */
  toolbar?: React.ReactNode;
  /** 搜索那一行下面、同样钉在头里的一条(上传进度、「一起换」的开关)。 */
  banner?: React.ReactNode;
  items: readonly T[];
  /** 点一格、或者键盘走到它按回车。 */
  onActivate: (item: T) => void;
  /** 先选再确认的(多选、替换):哪几格选中了;`order` 给了就在角上写先后(挂参考图的顺序就是挑的顺序)。 */
  selection?: { isSelected: (item: T) => boolean; order?: (item: T) => number; multiple?: boolean };
  /** 已经用上的那几格:返回写在格子上的那句(「已挂上」),这一格点不动;没用上返回 null。 */
  taken?: (item: T) => string | null;
  /** 几种素材混着列:格子下面写明是哪一种(同名的一张图和一段视频,光看名字分不出)。 */
  mixedKinds?: boolean;
  pending?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** 网格是空的时候说什么:一份都还没有,还是筛完没有,由调用方分。 */
  empty: { icon: React.ReactNode; title: string; body?: string };
  /** 清单是一页页从服务端取的:画到最后几行时叫一声,调用方接着取。没有下一页了就别给。 */
  onReachEnd?: () => void;
  /** 下一页还在路上:网格底下转一个圈。 */
  loadingMore?: boolean;
  /** 整个弹窗收拖进来的文件(见 ModalShell 的 dropzone)。 */
  dropzone?: React.ComponentProps<typeof ModalShell>["dropzone"];
  /** 钉在底部的确认区(多选时的「挂上 3 张」、替换时的「替换」)。点一格即挑中的不给。 */
  footer?: React.ReactNode;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const listId = React.useId();
  const searchRef = React.useRef<HTMLInputElement | null>(null);
  //: 滚动区在弹窗的 Portal 里,比这个组件晚一拍才挂上:元素存进 state,挂上时换一个 ref 对象,useVirtualRows 才会去盯
  //: 它的滚动和高度(一直拿同一个 ref 对象的话,它只在第一次、元素还不在的时候看过一眼 —— 往下滚,后面的行永远不画)。
  const [scroller, setScroller] = React.useState<HTMLDivElement | null>(null);
  const scrollerRef = React.useMemo(() => ({ current: scroller }), [scroller]);
  //: 网格从头底下滚过去时才画那条分隔线(和页面上的吸顶栏一个道理):没有东西滚过去时,它分的是空气。
  const [scrolled, setScrolled] = React.useState(false);

  //: 一行几格按网格自己的宽度算(和素材库同一条规则),只画看得见的那几行。
  const gridRef = React.useRef<HTMLDivElement | null>(null);
  const [gridElement, setGridElement] = React.useState<HTMLDivElement | null>(null);
  const attachGrid = React.useCallback((element: HTMLDivElement | null) => {
    gridRef.current = element;
    setGridElement(element);
  }, []);
  const gridWidth = useElementWidth(gridElement);
  const columns = Math.max(1, Math.floor((gridWidth + GRID_GAP_PX) / (TILE_MIN_PX + GRID_GAP_PX)));
  const rows = React.useMemo(() => {
    const out: T[][] = [];
    for (let at = 0; at < items.length; at += columns) out.push(items.slice(at, at + columns));
    return out;
  }, [items, columns]);
  const rowKeys = React.useMemo(() => rows.map((row) => `${columns}:${row[0].id}`), [rows, columns]);
  const tileWidth = gridWidth > 0 ? (gridWidth - GRID_GAP_PX * (columns - 1)) / columns : TILE_MIN_PX;
  const estimate = Math.round(((tileWidth - TILE_PAD_PX * 2) * 3) / 4 + TILE_PAD_PX * 2 + TILE_TEXT_PX + GRID_GAP_PX);
  const virtual = useVirtualRows({ keys: rowKeys, scrollRef: scrollerRef, listRef: gridRef, estimate });

  //: 画到倒数几行就要下一页。弹窗很高、第一页填不满时,一打开就画到了最后一行,接着要 —— 不用等人滚。
  const reachEnd = React.useRef(onReachEnd);
  reachEnd.current = onReachEnd;
  const wantsMore = Boolean(onReachEnd);
  React.useEffect(() => {
    if (wantsMore && !loadingMore && rows.length > 0 && rows.length - virtual.end <= PREFETCH_ROWS) reachEnd.current?.();
  }, [wantsMore, loadingMore, rows.length, virtual.end]);

  //: 高亮的那一格:回车挑它,Tab 进网格落在它上面。清单换了(搜了别的、换了种类)回到第一格;接着翻页不算换。
  const [active, setActive] = React.useState(0);
  const firstId = items[0]?.id;
  React.useEffect(() => setActive(0), [firstId]);
  const current = Math.min(active, Math.max(0, items.length - 1));
  //: 键盘走到的那一格可能还没画出来(只画看得见的几行):先滚过去,画出来之后再给它焦点。
  //: 走到的还是同一格(从搜索框 ↓ 进来)时 active 不变、不会重渲,所以另记一拍。
  const focusing = React.useRef(false);
  const [focusTick, bumpFocus] = React.useReducer((n: number) => n + 1, 0);
  const moveTo = (index: number) => {
    setActive(index);
    focusing.current = true;
    bumpFocus();
    virtual.reveal(Math.floor(index / columns));
  };
  React.useLayoutEffect(() => {
    if (!focusing.current) return;
    const tile = gridRef.current?.querySelector<HTMLElement>(`[data-tile-index="${current}"]`);
    if (!tile) return;
    focusing.current = false;
    tile.focus();
  }, [current, focusTick, virtual.start, virtual.end]);

  const activate = (item: T | undefined) => {
    if (item && !taken?.(item)) onActivate(item);
  };
  const searchKeys = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveTo(current);
    } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      activate(items[current]);
    }
  };
  const gridKeys = (event: React.KeyboardEvent<HTMLDivElement>) => {
    //: 从哪一格走:焦点所在的那一格(鼠标可能把高亮挪到了别处)。
    const from = Number((event.target as HTMLElement).closest("[data-tile-cell]")?.getAttribute("data-tile-cell") ?? current);
    const last = items.length - 1;
    const rowOf = (index: number) => Math.floor(index / columns);
    let next: number | null;
    if (event.key === "ArrowRight") next = from < last ? from + 1 : null;
    else if (event.key === "ArrowLeft") next = from > 0 ? from - 1 : null;
    else if (event.key === "ArrowDown") next = from + columns <= last ? from + columns : rowOf(from) < rowOf(last) ? last : null;
    else if (event.key === "ArrowUp") next = from - columns;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;
    event.preventDefault();
    if (next === null) return;
    //: 第一行再往上是搜索框:接着打字。
    if (next < 0) {
      searchRef.current?.focus();
      return;
    }
    moveTo(next);
  };

  //: 看大图左右翻的是眼下这份网格里的图和视频(同样的筛选、同样的搜索词)。
  const { openImagePreview } = useImagePreview();
  const gallery = React.useMemo(() => assetGallery(items), [items]);
  const preview = (item: T) => {
    const one = assetPreviewItem(item);
    if (one) openImagePreview({ ...one, gallery });
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      dropzone={dropzone}
      footer={footer}
      //: 宽到一行放得下五格,高度固定:翻页、换筛选时弹窗不跳,网格在里面滚。
      className="w-[min(960px,calc(100vw-32px))] h-[min(840px,85dvh)]"
      bodyClassName="flex flex-col overflow-hidden p-0 [scrollbar-gutter:auto]"
      header={
        <>
          {description ? <p className="m-0 text-ui-sm text-muted-foreground">{description}</p> : null}
          <div data-asset-grid-toolbar="" className="flex min-w-0 flex-wrap items-center gap-2">
            <SearchInput className="min-w-48 flex-1"
                ref={searchRef}
                autoFocus
                size="sm"
                aria-label={searchLabel}
                placeholder={searchLabel}
                value={query}
                maxLength={300}
                onChange={(event) => onQueryChange(event.target.value)}
                onKeyDown={searchKeys}
                aria-controls={listId} />
            {toolbar}
          </div>
          {banner}
        </>
      }
    >
      {/* 格子自己有 8px 内边距:滚动区左右留 16,缩略图和头里的搜索框左边对齐。 */}
      <div
        ref={setScroller}
        data-asset-grid-scroll=""
        data-scrolled={scrolled}
        onScroll={(event) => setScrolled(event.currentTarget.scrollTop > 0)}
        className={cn(
          "flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain border-t px-4 pt-1 transition-colors [scrollbar-gutter:stable]",
          scrolled ? "border-divider" : "border-transparent",
          footer ? "pb-2" : "pb-5",
        )}
      >
        {pending ? (
          <GridSkeleton />
        ) : error ? (
          <PageLoadError size="section" icon={<ImageIcon />} error={error} onRetry={onRetry} />
        ) : !items.length ? (
          <EmptyState size="section" icon={empty.icon} title={empty.title} body={empty.body} />
        ) : (
          <div
            ref={attachGrid}
            id={listId}
            role="listbox"
            aria-label={title}
            aria-multiselectable={selection?.multiple || undefined}
            onKeyDown={gridKeys}
          >
            {virtual.padTop > 0 && <div aria-hidden="true" style={{ height: virtual.padTop }} />}
            {rows.slice(virtual.start, virtual.end).map((row, offset) => {
              const rowIndex = virtual.start + offset;
              const key = rowKeys[rowIndex];
              return (
                <div
                  key={key}
                  ref={virtual.measure(key)}
                  role="none"
                  className="grid gap-x-1 pb-1"
                  style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
                >
                  {row.map((item, column) => {
                    const index = rowIndex * columns + column;
                    return (
                      <AssetTile
                        key={item.id}
                        asset={item}
                        index={index}
                        active={index === current}
                        selected={selection ? selection.isSelected(item) : null}
                        order={selection?.order ? selection.order(item) : null}
                        taken={taken?.(item) ?? null}
                        mixedKinds={mixedKinds}
                        locale={locale}
                        onActivate={() => activate(item)}
                        onHighlight={() => index !== active && setActive(index)}
                        onPreview={() => preview(item)}
                      />
                    );
                  })}
                </div>
              );
            })}
            <div aria-hidden="true" style={{ height: virtual.padBottom }} />
          </div>
        )}
        {loadingMore && (
          <div role="status" className="grid shrink-0 place-items-center py-3 text-muted-foreground">
            <Loader2 size={16} className="animate-mosael-spin" />
            <span className="sr-only">{t("pageLoading")}</span>
          </div>
        )}
      </div>
    </ModalShell>
  );
}

/** 一格的媒体字段(都在 media_info 里,顶层没有)。 */
type MediaFacts = { width?: number | null; height?: number | null; duration?: number | null; has_thumbnail?: boolean | null; format?: string | null };

function AssetTile({
  asset,
  index,
  active,
  selected,
  order,
  taken,
  mixedKinds,
  locale,
  onActivate,
  onHighlight,
  onPreview,
}: {
  asset: GridAsset;
  index: number;
  active: boolean;
  /** null:点一格即挑中,没有「选中」这回事 —— 那时 aria-selected 说的是高亮的那一格。 */
  selected: boolean | null;
  order: number | null;
  taken: string | null;
  mixedKinds: boolean;
  locale: string;
  onActivate: () => void;
  onHighlight: () => void;
  onPreview: () => void;
}) {
  const t = useI18n();
  const factsId = React.useId();
  const info = asset.media_info as MediaFacts;
  const name = asset.name || asset.original_filename || "";
  //: 第二行:是什么、多大。音频没有尺寸,写时长;文档写格式、页数、大小(和素材库的卡片同一句)。
  const size =
    asset.kind === "document"
      ? documentFacts(asset)
      : info.width && info.height
        ? `${info.width}×${info.height}`
        : asset.kind === "audio" && info.duration
          ? formatTimecode(info.duration)
          : "—";
  const facts = mixedKinds ? `${t(assetKindKey(asset.kind))} · ${size}` : size;
  //: 第三行:哪来的、多久以前。同名的几份就靠这一行分开;悬停看具体时间。
  const when = asset.created_at ? relativeTime(asset.created_at, locale) : "";
  const provenance = [t(assetOriginKey(asset)), when].filter(Boolean).join(" · ");
  const at = asset.created_at ? parseServerTime(asset.created_at).toLocaleString(locale) : null;
  const isSelected = selected === true;
  return (
    <div role="none" data-tile-cell={index} className="group/preview relative min-w-0">
      <button
        type="button"
        role="option"
        data-tile-index={index}
        data-asset-tile={asset.id}
        aria-selected={selected ?? active}
        aria-disabled={taken ? true : undefined}
        aria-label={name}
        aria-describedby={factsId}
        tabIndex={active ? 0 : -1}
        onClick={onActivate}
        onFocus={onHighlight}
        onMouseMove={onHighlight}
        className={cn(
          "grid w-full min-w-0 cursor-pointer content-start gap-2 rounded-lg border-0 bg-transparent p-2 text-left transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          //: 悬停不另画一层:鼠标挪到哪一格,高亮就挪到哪一格(onMouseMove),和键盘走到的是同一种底色,不会同时亮两格。
          active && "bg-secondary",
          taken && "cursor-default",
        )}
      >
        <span
          className={cn(
            "relative grid aspect-[4/3] w-full place-items-center overflow-hidden rounded-md border bg-panel-inset text-muted-foreground transition-[border-color,box-shadow]",
            isSelected ? "border-primary ring-2 ring-primary" : "border-border",
          )}
        >
          <TileFace asset={asset} dim={Boolean(taken)} />
          {asset.kind === "video" && info.duration ? (
            <span className="absolute bottom-1.5 right-1.5 inline-flex items-center gap-1 rounded-sm bg-[rgba(10,12,15,0.75)] px-[5px] py-px font-mono text-ui-2xs tabular-nums text-[#e8eaed]">
              <Play size={8} fill="currentColor" aria-hidden="true" />
              {formatTimecode(info.duration)}
            </span>
          ) : null}
          {isSelected && (
            <span className="absolute right-1.5 top-1.5 grid size-5 place-items-center rounded-full bg-action text-ui-2xs font-semibold text-action-foreground">
              {order !== null && order >= 0 ? order + 1 : <Check size={12} strokeWidth={2.5} />}
            </span>
          )}
          {taken && (
            <span className="absolute inset-x-1.5 bottom-1.5 inline-flex items-center justify-center gap-1 rounded-md bg-background/85 py-0.5 text-ui-2xs text-foreground backdrop-blur">
              <Check size={11} />
              {taken}
            </span>
          )}
        </span>
        <span className="grid min-w-0 gap-0.5 px-0.5">
          <Truncate className="text-ui-sm font-medium text-foreground">{name}</Truncate>
          <span id={factsId} className="grid min-w-0 gap-0.5 text-ui-xs text-muted-foreground">
            <Truncate className="tabular-nums">{facts}</Truncate>
            <Truncate hint={at}>{provenance}</Truncate>
          </span>
        </span>
      </button>
      {/* 按钮不能套按钮:「看大图」和这一格并排放,压在缩略图左上角。 */}
      {kindIsVisual(asset.kind) && <ViewFullSizeButton name={name} onOpen={onPreview} className="left-3.5 top-3.5" />}
    </div>
  );
}

/** 缩略图那一块:图和视频是缩略图(完整放进去,不裁),音频是波形,文档是第一页或图标。 */
function TileFace({ asset, dim }: { asset: GridAsset; dim: boolean }) {
  const [failed, setFailed] = React.useState(false);
  const info = asset.media_info as MediaFacts;
  //: 文档的封面是解析时渲的第一页(ADR 0031),还没有就画图标。
  const thumb = !failed && (kindIsVisual(asset.kind) || (asset.kind === "document" && Boolean(info.has_thumbnail)));
  if (thumb) {
    return (
      <img
        src={assetThumbnailUrl(asset.id)}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className={cn("absolute inset-0 size-full object-contain", dim && "opacity-40")}
      />
    );
  }
  if (asset.kind === "audio") return <Waveform seed={asset.id} />;
  if (asset.kind === "document") {
    const extension = /\.([a-z0-9]+)$/i.exec(asset.original_filename || asset.name || "")?.[1] ?? "";
    return (
      <span className="grid justify-items-center gap-1.5">
        <FileText size={28} strokeWidth={1.4} />
        <span className="text-ui-2xs font-semibold uppercase tracking-wide">{info.format || extension}</span>
      </span>
    );
  }
  const Icon = asset.kind === "video" ? Video : ImageIcon;
  return <Icon size={28} strokeWidth={1.4} />;
}

/**
 * 音频那一格:一条波形样的竖条。不是真的波形(那要把整段音频取回来解码),是按素材 id 定形的装饰 ——
 * 同一份每次长得一样,几段音频并排时也不是同一张图。
 */
function Waveform({ seed }: { seed: string }) {
  const bars = React.useMemo(() => waveform(seed, 32), [seed]);
  return (
    <svg viewBox="0 0 128 48" preserveAspectRatio="none" aria-hidden="true" className="h-1/3 w-3/5 text-primary/70">
      {bars.map((height, at) => (
        <rect key={at} x={at * 4 + 0.75} y={(48 - height) / 2} width={2.5} height={height} rx={1.25} fill="currentColor" />
      ))}
    </svg>
  );
}

/** 一串 0–46 的高度:伪随机(按 seed 定),相邻的平滑一点,两头收一点 —— 看着像一段声音。 */
function waveform(seed: string, count: number): number[] {
  let state = 0x811c9dc5;
  for (let i = 0; i < seed.length; i += 1) state = Math.imul(state ^ seed.charCodeAt(i), 0x01000193) >>> 0;
  const out: number[] = [];
  let level = 0.5;
  for (let i = 0; i < count; i += 1) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    level = level * 0.45 + (state / 2 ** 32) * 0.55;
    const envelope = 0.4 + 0.6 * Math.sin((Math.PI * (i + 0.5)) / count);
    out.push(Math.max(4, Math.round(level * envelope * 46)));
  }
  return out;
}

/** 还没取回来:和格子同样大小的骨架,到了原地换掉,不跳。 */
function GridSkeleton() {
  const t = useI18n();
  return (
    <div
      role="status"
      aria-busy="true"
      className="grid gap-x-1 gap-y-1"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${TILE_MIN_PX}px, 1fr))` }}
    >
      <span className="sr-only">{t("pageLoading")}</span>
      {Array.from({ length: 10 }, (_, index) => (
        <div key={index} aria-hidden="true" className="grid gap-2 p-2">
          <Skeleton className="aspect-[4/3] w-full rounded-md" />
          <div className="grid gap-1.5 px-0.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * 按种类筛:全应用的分段控件(segmentedListClass / segmentedItemClass 的 sm 档),和头里的搜索框、按钮一样 32px 高。
 * 画板挑素材(全部 / 图片 / 视频 / 音频 / 文档)和挂参考图(全部 / 图片 / 视频)都用它。
 */
export function AssetKindSwitch<V extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: V;
  options: readonly { value: V; label: string }[];
  onChange: (value: V) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={segmentedListClass("sm")}>
      {options.map((one) => (
        <button
          key={one.value}
          type="button"
          role="radio"
          aria-checked={value === one.value}
          className={segmentedItemClass(value === one.value, "sm")}
          onClick={() => onChange(one.value)}
        >
          {one.label}
        </button>
      ))}
    </div>
  );
}
