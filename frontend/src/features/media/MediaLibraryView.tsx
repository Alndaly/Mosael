import { assetKeys } from "@/api/queryKeys";
import { PageHeading, CollectionTabs } from "@/components/layout/StudioPage";
import { LayoutGrid, List, MoreHorizontal, Search } from "lucide-react";
import { Popover, PopoverTrigger, PopoverClose } from "@/components/ui/popover";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem, MenuItemBody, MenuSeparator } from "@/components/ui/menu";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import React from "react";
import { OPEN_ASSET_EVENT, useOpenRequest, useSectionEntry } from "@/lib/deepLink";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDot, Columns2, Download, FileAudio, FileImage, FileText, FileVideo, FolderOpen, ImagePlus, Layers, NotebookPen, Link2, ListChecks, AudioWaveform, Loader2, Pencil, Scissors, Tag, Trash2, Upload, X } from "lucide-react";

import { assetThumbnailUrl, convertVideoToGif, deleteAsset, renameAsset, setAssetTags, type AssetCard, type AssetQuery, type AssetSort, type Workspace } from "@/api/client";
import { UrlImportDialog } from "@/features/media/UrlImportDialog";
import { saveAssetToDisk } from "@/lib/download";
import { isImportableFile, useFileDrop } from "@/lib/useFileDrop";
import { useWriteBlocked } from "@/components/layout/useWriteBlocked";
import { assetKindKey, documentFacts, IMPORT_ACCEPT, kindHasSound, kindIsVisual } from "@/lib/assetKinds";
import { useSaveDocumentAsNote } from "@/features/media/useSaveDocumentAsNote";
import { toast } from "sonner";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { AssetCompareView } from "@/features/media/AssetCompareView";
import { VideoCompareView } from "@/features/media/VideoCompareView";
import { useAssetAudioActions } from "@/features/media/useAssetAudioActions";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { useRecorder } from "@/features/media/recordingContext";
import { AssetPreviewModalById } from "@/features/media/AssetPreviewModalById";
import type { MenuAction } from "@/components/app/ActionMenu";
import { useAssetDetails, useAssetFacets, useAssetPages } from "@/lib/assetQueries";
import { assetOriginKey, showsContainsAi } from "@/lib/assetOrigin";
import { useImportMediaFiles } from "@/features/media/useImportMediaFiles";
import { TagFilter } from "@/components/app/TagFilter";
import { SetAsReferenceDialog } from "@/features/entities/AssetEntities";
import { TAG_MATCHES, tagsOf, sortedTagCounts, type TagMatch } from "@/lib/tags";
import { TagChips } from "./TagChips";
import { TagsDialog } from "@/components/app/TagsDialog";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { assetGallery, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { ViewFullSizeButton } from "@/components/app/view-full-size";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { usePersistentSet, usePersistentTab } from "@/lib/usePersistentTab";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { useElementWidth } from "@/lib/useElementWidth";
import { useVirtualRows } from "@/lib/useVirtualRows";
import { cn } from "@/lib/utils";
import { formatShortDate, formatTimecode } from "@/lib/time";
import { Skeleton } from "@/components/ui/skeleton";

const KIND_FILTERS = ["all", "video", "audio", "image", "document"] as const;
type KindFilter = (typeof KIND_FILTERS)[number];

const SORT_KEYS = ["created", "updated", "name", "duration"] as const satisfies readonly AssetSort[];
type SortKey = (typeof SORT_KEYS)[number];

/**
 * 中间产物(某道工序逐条做出来的零件,见后端 domain/assets/intermediates)在界面上叫什么、是什么。
 * 素材库默认不列它们;筛选条上一枚「配音片段 985」按下去才看。后端多了一种而这里没写的,不摆入口。
 */
const INTERMEDIATE_COPY: Record<string, { label: MessageKey; notice: MessageKey }> = {
  dub_line: { label: "mediaIntermediate_dub_line", notice: "mediaIntermediateHint_dub_line" },
  lipsync_chunk: { label: "mediaIntermediate_lipsync_chunk", notice: "mediaIntermediateHint_lipsync_chunk" },
};

/** 网格:一张卡片至少这么宽,一行能放几张就放几张(此前的 `repeat(auto-fill, minmax(220px, 1fr))`)。 */
const CARD_MIN_PX = 220;
/** 网格的列间距、行间距(gap-x-6 / pb-7):算一行几张、估一行多高都要用。 */
const GRID_GAP_X_PX = 24;
const GRID_GAP_Y_PX = 28;
/** 卡片缩略图下面那几行字大约多高;一行真画出来之后按量到的算,这只是还没画时的估计。 */
const CARD_TEXT_PX = 80;
/** 列表一行多高(128×80 的缩略图上下各 16,加一条分隔线)。 */
const LIST_ROW_PX = 113;
/** 已经画到倒数第几行时去取下一页:人滚到底之前,下一页已经到了。 */
const PREFETCH_ROWS = 3;

/**
 * 素材库 —— **工作区级**资源池。素材归属工作区(Asset.workspace_id 必填;project_id 可空,
 * 删项目只置空),所以这一页不带项目语境:列出整个工作区的素材,导入也不挂项目。
 * 需要"属于某个项目"的素材,从剪辑页导入。
 */
/** 卡片和完整详情都认得出的那几项:⋯ 菜单、右键、详情头部的动作只用到这些(改名、打标签、设为参考图、下载、删除)。 */
type ActionTarget = Pick<AssetCard, "id" | "name" | "original_filename" | "workspace_id" | "kind" | "tags">;

export function MediaLibraryView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  //: 只读成员导入不了、改不了、删不了素材:写入口灰掉并说为什么,拖进来也不收(体检 D62,和定时任务页同一个做法)。
  //: 下载、对比、看详情照常。
  const writeBlocked = useWriteBlocked(workspace.role);
  const qc = useQueryClient();
  const { openRecorder } = useRecorder();
  const [renaming, setRenaming] = React.useState<ActionTarget | null>(null);
  const [deleting, setDeleting] = React.useState<ActionTarget | null>(null);
  //: 详情按 id 开(AssetPreviewModalById 自己取完整字段):列表只带卡片字段,深链点名的那一份也不一定在已经翻到的几页里。
  const [previewingId, setPreviewingId] = React.useState<string | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [editingTags, setEditingTags] = React.useState<ActionTarget | null>(null);
  //: 右键「设为某个资产的参考图…」(ADR 0027):图片和视频能当参考图。
  const [referencing, setReferencing] = React.useState<ActionTarget | null>(null);
  // 筛选和排序是**这个人怎么用素材库**的一部分,不是这一刻的临时值 —— 切走再回来不该重置。
  // 搜索词是另一回事:它是"我此刻在找什么",留着反而会让人以为库里只有这几条。
  const [kindFilter, setKindFilter] = usePersistentTab<KindFilter>("media-kind", "all", KIND_FILTERS);
  const [search, setSearch] = React.useState("");
  //: 发给服务端的是停手之后的那个词:输入框照常跟手,不为每一个字发一次请求。
  const settledSearch = useDebouncedValue(search.trim());
  const [display, setDisplay] = usePersistentTab<"grid" | "list">("media-display", "grid", ["grid", "list"]);
  const [sortKey, setSortKey] = usePersistentTab<SortKey>("media-sort", "created", SORT_KEYS);
  const [comparing, setComparing] = React.useState(false);
  const [batchTagging, setBatchTagging] = React.useState(false);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const [urlImportOpen, setUrlImportOpen] = React.useState(false);
  const importInputRef = React.useRef<HTMLInputElement>(null);
  const filtersRef = React.useRef<HTMLDivElement>(null);
  const [filtersStuck, setFiltersStuck] = React.useState(false);
  const [actionMenuId, setActionMenuId] = React.useState<string | null>(null);

  //: 看素材库(空串),还是某一种中间产物(逐句配音的一句……)。它是「这一刻在看什么」,不记住:下次进来照旧是素材库 ——
  //: 停在配音片段上的话,人会以为素材库里只剩这些。
  const [shelf, setShelf] = React.useState("");
  //: 页签上的数字、标签筛选的候选:整个工作区的(素材库,或眼下看的那一种中间产物),不跟着搜索和这一页走
  //: (见后端 domain/assets/listing)。另带着每种中间产物各几份 —— 切过去的入口上写着它。标题旁的数说的
  //: 一直是素材库(看配音片段时写着「素材 985」会让人以为素材库里就是这些),所以素材库的那份总要有;看素材库时
  //: 两个是同一个查询。
  const libraryFacets = useAssetFacets(workspace.id);
  const facets = useAssetFacets(workspace.id, { intermediate: shelf });
  const intermediates = Object.entries(facets.data?.intermediates ?? {}).filter(
    ([kind, count]) => count > 0 && kind in INTERMEDIATE_COPY,
  );
  const tagCount = React.useMemo(() => sortedTagCounts(facets.data?.tags ?? {}), [facets.data]);
  const allTags = React.useMemo(() => [...tagCount.keys()], [tagCount]);

  // 标签筛选同理,而且可以同时勾几个。合法值是**动态的**(标签会被删),存着一个已经不存在的标签时
  // 当作没勾 —— 否则素材库会空得莫名其妙。
  const [tagFilter, setTagFilter] = usePersistentSet("media-tags", facets.data === undefined ? undefined : allTags);
  const [tagMatch, setTagMatch] = usePersistentTab<TagMatch>("media-tag-match", "all", TAG_MATCHES);

  //: 看哪些:种类、搜索、标签、排序都交给服务端,这里只拿一页一页的卡片。
  const query: AssetQuery = {
    workspace_id: workspace.id,
    kind: kindFilter === "all" ? undefined : [kindFilter],
    q: settledSearch || undefined,
    tag: tagFilter.length > 0 ? tagFilter : undefined,
    tag_match: tagMatch,
    intermediate: shelf || undefined,
    sort: sortKey,
  };
  const assets = useAssetPages(query);
  const visible = assets.items;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = assets;
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  //: 只画看得见的那几行(见 useVirtualRows)。网格按宽度分行,一行一个键 —— 行首那一份的 id 加上一行几张。
  const rowsRef = React.useRef<HTMLDivElement | null>(null);
  const [rowsElement, setRowsElement] = React.useState<HTMLDivElement | null>(null);
  const attachRows = React.useCallback((element: HTMLDivElement | null) => {
    rowsRef.current = element;
    setRowsElement(element);
  }, []);
  const gridWidth = useElementWidth(rowsElement);
  const columns = display === "list" ? 1 : Math.max(1, Math.floor((gridWidth + GRID_GAP_X_PX) / (CARD_MIN_PX + GRID_GAP_X_PX)));
  const rows = React.useMemo(() => {
    const out: AssetCard[][] = [];
    for (let at = 0; at < visible.length; at += columns) out.push(visible.slice(at, at + columns));
    return out;
  }, [visible, columns]);
  const rowKeys = React.useMemo(() => rows.map((row) => `${columns}:${row[0].id}`), [rows, columns]);
  const cardWidth = gridWidth > 0 ? (gridWidth - GRID_GAP_X_PX * (columns - 1)) / columns : CARD_MIN_PX;
  const estimate = display === "list" ? LIST_ROW_PX : Math.round((cardWidth * 9) / 16 + CARD_TEXT_PX + GRID_GAP_Y_PX);
  const virtual = useVirtualRows({ keys: rowKeys, scrollRef: scrollerRef, listRef: rowsRef, estimate });
  //: 画到倒数几行就去取下一页。屏幕很高、第一页填不满时,一打开就画到了最后一行,接着取 —— 不用等人滚。
  React.useEffect(() => {
    if (rows.length - virtual.end <= PREFETCH_ROWS && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [rows.length, virtual.end, hasNextPage, isFetchingNextPage, fetchNextPage]);

  //: `#/media?asset=<id>` 直接打开那一份的详情(画板上的文档格、智能体的引用胶囊跳过来):开一次就把参数摘掉 ——
  //: 否则关掉详情再回到这一页又弹出来。按 id 开,不等它出现在列表里。
  React.useEffect(() => {
    const wanted = new URLSearchParams(window.location.hash.split("?")[1] || "").get("asset");
    if (!wanted) return;
    setPreviewingId(wanted);
    window.history.replaceState(null, "", window.location.hash.split("?")[0] || "#/media");
  }, []);
  // 多选的状态机是共用的(见 lib/useMultiSelect)—— 素材、发布记录、工作流三处同一份。
  const { selectMode, enter: enterSelectMode, selectedIds, toggle: toggleSelected, selectAll, allSelected, clear: clearSelection, exit: exitSelectMode } =
    useMultiSelect(visible, (asset) => asset.id);
  //: 「全选」要的是满足条件的**全部**(没翻到的那几页先取回来),不是已经滚到的这些。
  const toggleSelectAll = async () => {
    if (!hasNextPage) return selectAll(visible);
    selectAll(await assets.loadAll());
  };
  /** 选中项里能参与对比的:图片和视频各是一套对比,**不混** —— 图片比的是同一处细节(联动缩放),
   *  视频比的是同一时刻(联动播放)。混选时两套都不成立,按钮禁用并说明。 */
  const selectedAssets = React.useMemo(
    () => visible.filter((asset) => selectedIds.has(asset.id)),
    [visible, selectedIds],
  );
  const compareKind: "image" | "video" | null = React.useMemo(() => {
    const kinds = new Set(selectedAssets.map((asset) => asset.kind));
    if (kinds.size !== 1) return null;
    const [only] = kinds;
    return only === "image" || only === "video" ? only : null;
  }, [selectedAssets]);
  const comparable = compareKind ? selectedAssets : [];
  //: 对比要完整字段(宽高、时长、代理):点「对比」时才按 id 取详情。
  const comparedDetails = useAssetDetails(comparing ? comparable.map((asset) => asset.id) : []).byId;
  const compared = comparable.flatMap((asset) => comparedDetails.get(asset.id) ?? []);
  const refresh = () => qc.invalidateQueries({ queryKey: assetKeys.everywhere() });

  //: 关掉详情,焦点回到这一份的卡片上:详情是按 id 开的,没有一颗「触发器」可还,此前键盘 Esc 关掉之后焦点掉回 body,
  //: 几百张的网格里得从页面顶上重新 Tab(体检 UM-24)。卡片不在眼前(虚拟列表滚走了、从别处深链进来)就不管。
  const closePreview = () => {
    const closed = previewingId;
    setPreviewingId(null);
    if (!closed) return;
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-asset-opener="${closed}"]`)?.focus());
  };

  // Cmd+K 面板选中素材后跳转到本页并直接打开详情(统一先进详情卡,图片也一样,要看大图再从卡里点开)。
  useOpenRequest(OPEN_ASSET_EVENT, (assetId) => {
    setPreviewingId(assetId);
  });

  // 工作区级导入:不挂 project_id,该工作区下所有项目都能用。按钮多选和拖进来是同一条路。
  const importFiles = useImportMediaFiles({ workspaceId: workspace.id });
  const saveAsNote = useSaveDocumentAsNote();
  const convertGif = useMutation({
    mutationFn: (assetId: string) => convertVideoToGif(assetId),
    onSuccess: () => toast.success(t("assetConvertGifQueued")),
    onError: (error: Error) => toast.error(error.message),
  });
  const { separate: separateAudio, denoise, denoiseDialog } = useAssetAudioActions();
  const drop = useFileDrop((files) => importFiles.mutate(files), isImportableFile);
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameAsset(id, name),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setRenaming(null);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: (_, id) => {
      setDeleteError(null);
      //: 从详情里删的:那一份没了,详情跟着关。
      setPreviewingId((current) => (current === id ? null : current));
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
    onError: (error) => setDeleteError(String((error as Error).message)),
  });
  const saveTags = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => setAssetTags(id, tags),
    onSuccess: () => {
      setEditingTags(null);
      void refresh();
    },
  });
  // 批量打标:并集合并到每个选中素材上,已有标签保留。
  const batchAddTags = useMutation({
    mutationFn: async (tags: string[]) => {
      const targets = visible.filter((asset) => selectedIds.has(asset.id));
      await Promise.all(
        targets.map((asset) => {
          const merged = [...tagsOf(asset)];
          for (const tag of tags) if (!merged.includes(tag)) merged.push(tag);
          return setAssetTags(asset.id, merged);
        }),
      );
    },
    onSuccess: () => {
      setBatchTagging(false);
      void refresh();
    },
  });
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 逐个尝试,失败的留下并提示。(被时间线引用**不再**是失败的理由:那些片段会转成
      // 脱机占位。这里剩下的是权限、文件被占用这类真正的失败。)
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deleteAsset(id);
        } catch (error) {
          const asset = visible.find((item) => item.id === id);
          failures.push(`${asset?.name ?? id}: ${String((error as Error).message)}`);
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setBatchDeleting(false);
      clearSelection();
      if (failures.length > 0) setDeleteError(failures.join("\n"));
      void refresh();
    },
  });

  // 「从起点进来」(统计页的素材总数):看的是**全部**素材 —— 记住的类型、标签筛选这回不作数,
  // 否则点「素材 128」进来只看到其中 12 条。排序、网格/列表是怎么看,不是看哪些,照旧。
  useSectionEntry("media", () => {
    setPreviewingId(null);
    setKindFilter("all");
    setTagFilter([]);
    setShelf("");
  });
  //: 一份都没有(不是「筛完没有」):整个工作区的计数说了算。素材库是空的、却有配音片段时,筛选条照旧在 ——
  //: 切过去的入口在上面。
  const libraryEmpty = libraryFacets.data?.total === 0;
  const nothingAtAll = libraryEmpty && intermediates.length === 0;
  const kindCount = (kind: KindFilter): number | undefined =>
    facets.data === undefined ? undefined : kind === "all" ? facets.data.total : (facets.data.kinds[kind] ?? 0);

  //: 「看大图」左右翻的是**眼下这一格网格**:同样的筛选、同样的排序、已经翻到的那几页里的图和视频。
  const { openImagePreview } = useImagePreview();
  const gallery = React.useMemo(() => assetGallery(visible), [visible]);
  const viewFullSize = (asset: AssetCard) => {
    const item = assetPreviewItem(asset);
    if (item) openImagePreview({ ...item, gallery });
  };

  //: 详情头部那一排操作:和卡片的 ⋯ / 右键同一组动作,详情里也能改名、打标签、删(体检 UM-13)。
  const detailActions = (asset: ActionTarget): MenuAction[] => [
    { label: t("assetSaveLocal"), icon: <Download />, onSelect: () => saveAssetToDisk(asset) },
    { label: t("rename"), icon: <Pencil />, disabledReason: writeBlocked?.brief, onSelect: () => setRenaming(asset) },
    { label: t("editTags"), icon: <Tag />, disabledReason: writeBlocked?.brief, onSelect: () => setEditingTags(asset) },
    ...(kindIsVisual(asset.kind) ? [{ label: t("assetSetAsReference"), icon: <Layers />, disabledReason: writeBlocked?.brief, onSelect: () => setReferencing(asset) }] : []),
    ...(asset.kind === "document" ? [{ label: t("docSaveAsNote"), icon: <NotebookPen />, disabled: saveAsNote.isPending, disabledReason: writeBlocked?.brief, onSelect: () => saveAsNote.mutate(asset.id) }] : []),
    ...(asset.kind === "video" ? [{ label: t("assetConvertGif"), icon: <ImagePlus />, disabled: convertGif.isPending, disabledReason: writeBlocked?.brief, onSelect: () => convertGif.mutate(asset.id) }] : []),
    ...(kindHasSound(asset.kind)
      ? [
          { label: t("separateAudio"), icon: <Scissors />, disabled: separateAudio.isPending, disabledReason: writeBlocked?.brief, onSelect: () => separateAudio.mutate(asset.id) },
          { label: t("denoiseAction"), icon: <AudioWaveform />, disabledReason: writeBlocked?.brief, onSelect: () => denoise(asset.id) },
        ]
      : []),
    { label: t("delete"), icon: <Trash2 />, destructive: true, disabledReason: writeBlocked?.brief, onSelect: () => setDeleting(asset) },
  ];

  /** 一张卡片(网格)或一行(列表):点开详情 / 选择模式下勾选,⋯ 和右键是同一张菜单;图和视频角上还有一颗「看大图」。 */
  const renderAsset = (asset: AssetCard) => (
    <ContextMenu key={asset.id} onOpenChange={open => { if (open) setActionMenuId(null); }}>
      <ContextMenuTrigger asChild>
        <div
          className="group group/preview relative cursor-pointer"
          onClick={() => {
            // 图片也先进详情卡(看得到尺寸/来源/标签等),要看大图再从卡里点开。
            if (selectMode) toggleSelected(asset.id);
            else setPreviewingId(asset.id);
          }}
        >
          {/* 读屏念的名字:逐句配音的一句名字都一样,带上念的那句话才分得清。 */}
        <button type="button" data-asset-opener={asset.id} className="absolute inset-0 z-[1] rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={asset.media_info.line_text ? `${asset.name}: ${asset.media_info.line_text}` : asset.name} />
          <AssetTile asset={asset} list={display === "list"} selected={selectMode && selectedIds.has(asset.id)} />
          {/* 点卡片是开详情(看尺寸、来源、标签)、勾选模式里是勾选;看大图是另一件事,单独一颗,摆在缩略图左上角。 */}
          {kindIsVisual(asset.kind) && (
            <ViewFullSizeButton name={asset.name} onOpen={() => viewFullSize(asset)} className={display === "list" ? "left-1.5 top-5" : "left-2 top-2"} />
          )}
          {/* 列表行里勾选圈放在行右侧、垂直居中 —— 右上角是给卡片的,一行只有 80px 高,贴在顶上看着像掉了。 */}
          {selectMode && <SelectionCheck selected={selectedIds.has(asset.id)} className={display === "list" ? "right-3 top-1/2 -translate-y-1/2" : undefined} />}
          {!selectMode && <div className="absolute right-2 top-2 z-10" onClick={e => e.stopPropagation()}>
            <Popover open={actionMenuId === asset.id} onOpenChange={open => setActionMenuId(current => open ? asset.id : current === asset.id ? null : current)}><PopoverTrigger asChild><IconButton variant="secondary" size="icon-xs" label={`${t("studioActions")}: ${asset.name}`} aria-haspopup="menu"><MoreHorizontal /></IconButton></PopoverTrigger>
            <MenuContent label={t("studioActions")} align="end" onCloseAutoFocus={event => { if (actionMenuId && actionMenuId !== asset.id) event.preventDefault(); }}>
              <PopoverClose asChild><MenuItem icon={<Download />} label={t("assetSaveLocal")} onClick={() => saveAssetToDisk(asset)} /></PopoverClose>
              <PopoverClose asChild><MenuItem icon={<Pencil />} label={t("rename")} disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => setRenaming(asset)} /></PopoverClose>
              <PopoverClose asChild><MenuItem icon={<Tag />} label={t("editTags")} disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => setEditingTags(asset)} /></PopoverClose>
              {kindIsVisual(asset.kind) && <PopoverClose asChild><MenuItem icon={<Layers />} label={t("assetSetAsReference")} disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => setReferencing(asset)} /></PopoverClose>}
              {asset.kind === "document" && <PopoverClose asChild><MenuItem icon={saveAsNote.isPending ? <Loader2 className="animate-spin" /> : <NotebookPen />} label={t("docSaveAsNote")} disabled={saveAsNote.isPending || Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => saveAsNote.mutate(asset.id)} /></PopoverClose>}
              {asset.kind === "video" && <PopoverClose asChild><MenuItem icon={convertGif.isPending ? <Loader2 className="animate-spin" /> : <ImagePlus />} label={t("assetConvertGif")} disabled={convertGif.isPending || Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => convertGif.mutate(asset.id)} /></PopoverClose>}
              {kindHasSound(asset.kind) && <PopoverClose asChild><MenuItem icon={separateAudio.isPending ? <Loader2 className="animate-spin" /> : <Scissors />} label={t("separateAudio")} disabled={separateAudio.isPending || Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => separateAudio.mutate(asset.id)} /></PopoverClose>}
              {kindHasSound(asset.kind) && <PopoverClose asChild><MenuItem icon={<AudioWaveform />} label={t("denoiseAction")} disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => denoise(asset.id)} /></PopoverClose>}
              <MenuSeparator />
              <PopoverClose asChild><MenuItem icon={<Trash2 />} label={t("delete")} destructive disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => setDeleting(asset)} /></PopoverClose>
            </MenuContent></Popover>
          </div>}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => saveAssetToDisk(asset)}>
          <MenuItemBody icon={<Download />} label={t("assetSaveLocal")} />
        </ContextMenuItem>
        <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => setRenaming(asset)}>
          <MenuItemBody icon={<Pencil />} label={t("rename")} description={writeBlocked?.brief} />
        </ContextMenuItem>
        <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => setEditingTags(asset)}>
          <MenuItemBody icon={<Tag />} label={t("editTags")} description={writeBlocked?.brief} />
        </ContextMenuItem>
        {kindIsVisual(asset.kind) && (
          <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => setReferencing(asset)}>
            <MenuItemBody icon={<Layers />} label={t("assetSetAsReference")} description={writeBlocked?.brief} />
          </ContextMenuItem>
        )}
        {asset.kind === "document" && (
          <ContextMenuItem disabled={saveAsNote.isPending || Boolean(writeBlocked)} onSelect={() => saveAsNote.mutate(asset.id)}>
            <MenuItemBody icon={<NotebookPen />} label={t("docSaveAsNote")} description={writeBlocked?.brief} />
          </ContextMenuItem>
        )}
        {asset.kind === "video" && (
          <ContextMenuItem disabled={convertGif.isPending || Boolean(writeBlocked)} onSelect={() => convertGif.mutate(asset.id)}>
            <MenuItemBody icon={convertGif.isPending ? <Loader2 className="animate-spin" /> : <ImagePlus />} label={t("assetConvertGif")} description={writeBlocked?.brief} />
          </ContextMenuItem>
        )}
        {kindHasSound(asset.kind) && (
          <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => denoise(asset.id)}>
            <MenuItemBody icon={<AudioWaveform />} label={t("denoiseAction")} description={writeBlocked?.brief} />
          </ContextMenuItem>
        )}
        {kindHasSound(asset.kind) && (
          <ContextMenuItem disabled={separateAudio.isPending || Boolean(writeBlocked)} onSelect={() => separateAudio.mutate(asset.id)}>
            <MenuItemBody icon={separateAudio.isPending ? <Loader2 className="animate-spin" /> : <Scissors />} label={t("separateAudio")} description={writeBlocked?.brief} />
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" disabled={Boolean(writeBlocked)} onSelect={() => setDeleting(asset)}>
          <MenuItemBody icon={<Trash2 />} label={t("delete")} description={writeBlocked?.brief} />
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );

  const kindLabel: Record<KindFilter, string> = {
    all: t("kindAll"),
    video: t("kindVideo"),
    audio: t("kindAudio"),
    image: t("kindImage"),
    document: t("kindDocument"),
  };

  return (
    // 两层:外层不滚,只做定位上下文;里层是滚动区。遮罩挂在**外层**上 ——
    // 挂在滚动容器里的话,absolute 会跟着内容一起滚走,滚到一半松手时提示已经在屏幕外了。
    <div className="relative h-full min-h-0" {...(writeBlocked ? {} : drop.handlers)}>
      {/* inset-0 一点不留:留边就会在四角露出没被盖住的缝。落点是整块区域,不是某个方框。 */}
      {(drop.active || importFiles.isPending) && (
        <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
          <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
            {importFiles.isPending ? (
              <>
                <Loader2 size={20} className="animate-mosael-spin" />
                {t("mediaDropUploading")}
              </>
            ) : (
              <>
                <Upload size={20} />
                {t("mediaDropHint")}
              </>
            )}
          </span>
        </div>
      )}
      <div ref={scrollerRef} data-media-scroll className="flex h-full min-h-0 flex-col items-stretch overflow-auto px-6 pb-7 xl:px-9 xl:pb-8 [&>*]:shrink-0"
        onScroll={(event) => {
          const filters = filtersRef.current;
          setFiltersStuck(!!filters && event.currentTarget.scrollTop > 0 && filters.getBoundingClientRect().top <= event.currentTarget.getBoundingClientRect().top + 1);
        }}
      >
      <PageHeading title={t("navMedia")} description={t("studioMediaDesc")} count={libraryFacets.data?.total} className="py-7 xl:py-8" actions={<>
              <input
                ref={importInputRef}
                type="file"
                accept={IMPORT_ACCEPT}
                multiple
                className="hidden"
                disabled={importFiles.isPending}
                onChange={(event) => {
                  const files = [...(event.currentTarget.files ?? [])];
                  if (files.length > 0) importFiles.mutate(files);
                  event.currentTarget.value = "";
                }}
              />
              <Hint disabledReason={writeBlocked?.reason}>
                <Button size="default" loading={importFiles.isPending} disabled={Boolean(writeBlocked)} onClick={() => importInputRef.current?.click()}>
                  <ImagePlus />{t("import")}
                </Button>
              </Hint>
              <Hint disabledReason={writeBlocked?.reason}>
                <Button variant="outline" size="default" disabled={Boolean(writeBlocked)} onClick={() => setUrlImportOpen(true)}>
                  <Link2 size={13} /> {t("urlImport")}
                </Button>
              </Hint>
              <Hint disabledReason={writeBlocked?.reason}>
                <Button variant="outline" size="default" disabled={Boolean(writeBlocked)} onClick={() => openRecorder()}>
                  <CircleDot size={13} /> {t("record")}
                </Button>
              </Hint>
      </>} />
      {/* 顶部工具条 + 标签筛选 sticky 吸顶:滚动素材网格时保持可见。顶部内边距放在本 sticky 头上
          (滚动容器不留 pt),吸顶时才能严丝合缝贴顶、不露出上一行卡片;-mx 铺满宽度,底色盖住滚上来的卡片。 */}
      {/* **底色不写在这儿。** `data-stuck` 一交出去,底色和分割线就由 .workspace-sticky 按
          "有没有东西从下面滚过去"淡入淡出(见 design/tokens.css)—— 页面还没动过的时候,
          这条栏不该先把背景切掉一块。写死一个 bg-* 会盖过那条规则,等于把开关按住不放。 */}
      {/* 负外边距和外壳的内边距**是同一个数**:它靠 -mx 把自己拉到容器边缘,好让 sticky 时的
          底色铺满整宽。外壳从 px-3.5 收到 px-2 之后这层耦合就断了 —— 工具条比容器宽出 12px,
          整页于是能左右滚(真机)。两个数写在一起,下次改 padding 时才看得见要一起改。 */}
      {!nothingAtAll && (
        <div ref={filtersRef} data-stuck={filtersStuck} className="workspace-sticky sticky top-0 z-20 -mx-6 flex flex-col gap-3 border-b border-divider px-6 py-3 xl:-mx-9 xl:px-9">
          {/* **一行,按"这是哪一类动作"分三段。**
              类型标签是最粗的那一刀,锚在左边 —— 它的下划线指示器需要一条稳定的左基线;
              搜索/排序/标签是在这一刀之内再筛再排,占中间那段弹性宽度(搜索吃掉全部余量,
              它是这里最常用、也最吃宽度的一个);视图切换和多选改的不是"看哪些",是"怎么看、
              要不要动它们",所以推到最右,并用一条竖线断开。

              **窄了就换行,不横向滚。** 这一行里全是要读的标签和要打字的输入框,滚动条会把
              其中一半藏起来 —— 而它们没有主次之分,藏哪一半都是错的。 */}
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3" data-media-filter-row>
            <CollectionTabs value={kindFilter} onChange={setKindFilter} label={t("mediaKindGroup")} items={KIND_FILTERS.map(kind => ({ value: kind, label: kindLabel[kind], count: kindCount(kind) }))} />
            {/* 中间产物的入口:素材库默认不列它们,在这里按下去看(再按一下回到素材库)。数字是那一种一共几份。
                紧跟在类型标签后面 —— 它和类型一样是「看哪些」,也和页签一样带着数。 */}
            {intermediates.map(([kind, count]) => (
              <Button
                key={kind}
                variant="outline"
                size="default"
                aria-pressed={shelf === kind}
                aria-label={`${t(INTERMEDIATE_COPY[kind].label)} ${count}`}
                className={cn("shrink-0 border-border bg-control", shelf === kind && "border-primary/40 bg-accent text-primary")}
                onClick={() => setShelf((current) => (current === kind ? "" : kind))}
              >
                <Layers size={13} />
                {t(INTERMEDIATE_COPY[kind].label)}
                <span className="text-ui-xs tabular-nums text-muted-foreground">{count}</span>
              </Button>
            ))}
            {/* 多了「配音片段」那一枚,一行就放不下了(1440 宽的窗口里差一百多像素):搜索那一段整段换到第二行、铺满,
                视图切换留在第一行最右 —— 不把搜索框和标签筛选挤到压在一起,竖线也不会悬在第二行的行首。 */}
            <div className={cn("flex min-w-0 flex-1 items-center gap-2", intermediates.length > 0 && "order-last basis-full")}>
              <div className="relative min-w-40 flex-1">
                <Search size={16} className="pointer-events-none absolute left-3 top-3 text-muted-foreground" />
                <Input aria-label={t("searchAssets")} className="border-border bg-control pl-9" value={search} placeholder={t("searchAssets")} onChange={(event) => setSearch(event.target.value)} />
              </div>
              <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
                <SelectTrigger className="w-auto min-w-32 border-border bg-control" aria-label={t("sortNewest")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="created">{t("sortNewest")}</SelectItem>
                  <SelectItem value="updated">{t("sortUpdated")}</SelectItem>
                  <SelectItem value="name">{t("sortName")}</SelectItem>
                  <SelectItem value="duration">{t("sortDuration")}</SelectItem>
                </SelectContent>
              </Select>
              {allTags.length > 0 && <TagFilter counts={tagCount} value={tagFilter} onChange={setTagFilter} match={tagMatch} onMatchChange={setTagMatch} />}
            </div>
            {/* 竖线只在这一段真的排在别人右边时才画 —— 换行之后它会变成一条悬在行首的线。 */}
            <div className={cn("flex items-center gap-2 border-divider max-lg:w-full", intermediates.length > 0 ? "lg:ml-auto" : "lg:border-l lg:pl-4")}>
              <div role="group" className="flex gap-1" aria-label={t("studioGridView")}>
                <IconButton variant="outline" size="default" className={cn("px-3", display === "grid" && "border-primary/40 bg-accent text-primary")} label={t("studioGridView")} aria-pressed={display === "grid"} onClick={() => setDisplay("grid")}><LayoutGrid /></IconButton>
                <IconButton variant="outline" size="default" className={cn("px-3", display === "list" && "border-primary/40 bg-accent text-primary")} label={t("studioListView")} aria-pressed={display === "list"} onClick={() => setDisplay("list")}><List /></IconButton>
              </div>
              <Button variant="outline" className="ml-auto" aria-pressed={selectMode} onClick={() => selectMode ? exitSelectMode() : enterSelectMode()}>
                {selectMode ? <X /> : <Check />}{selectMode ? t("cancel") : t("mediaSelectMode")}
              </Button>
            </div>
          </div>
          {selectMode && <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-3" role="group" aria-label={t("mediaSelectMode")}>

                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                    {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
                  </span>
                  <Button variant="outline" size="default" loading={assets.isFetchingNextPage} onClick={() => void toggleSelectAll()}>
                    <ListChecks size={13} />{" "}
                    {allSelected(visible) && !hasNextPage ? t("mediaDeselectAll") : t("mediaSelectAll")}
                  </Button>
                  {/* 图片:联动缩放平移;视频:联动播放。选的不是同一种、或不到两个时禁用并说明原因。 */}
                  <Hint disabledReason={comparable.length < 2 ? t("mediaCompareHint") : undefined}>
                    <Button
                      variant="outline"
                      size="default"
                      disabled={comparable.length < 2}
                      onClick={() => setComparing(true)}
                    >
                      <Columns2 size={13} /> {t("mediaCompare")}
                    </Button>
                  </Hint>
                  <Hint disabledReason={writeBlocked?.reason}>
                    <Button
                      variant="outline"
                      size="default"
                      disabled={selectedIds.size === 0 || Boolean(writeBlocked)}
                      onClick={() => setBatchTagging(true)}
                    >
                      <Tag size={13} /> {t("addTags")}
                    </Button>
                  </Hint>
                  <Hint disabledReason={writeBlocked?.reason}>
                    <Button
                      variant="outline"
                      size="default"
                      className="hover:border-destructive/50 hover:text-destructive"
                      disabled={selectedIds.size === 0 || Boolean(writeBlocked)}
                      onClick={() => setBatchDeleting(true)}
                    >
                      <Trash2 size={13} /> {t("delete")}
                    </Button>
                  </Hint>
                  <Button variant="outline" size="default" onClick={exitSelectMode}>
                    <X size={13} /> {t("cancel")}
                  </Button>

          </div>}
          {/* 正在看中间产物:说清它们是什么、时间线上照常在用 —— 免得人以为素材库只剩这些,或者以为它们丢过。 */}
          {shelf && INTERMEDIATE_COPY[shelf] && (
            <div role="note" className="flex flex-wrap items-center gap-2 border-t border-divider pt-3 text-ui-sm text-muted-foreground">
              <Layers size={14} className="shrink-0" />
              <span className="min-w-0 flex-1">{t(INTERMEDIATE_COPY[shelf].notice)}</span>
              <Button variant="outline" size="default" onClick={() => setShelf("")}>
                <X size={13} /> {t("mediaBackToLibrary")}
              </Button>
            </div>
          )}
        </div>
      )}
      <UrlImportDialog
        open={urlImportOpen}
        onOpenChange={setUrlImportOpen}
        workspace={workspace}
        // 下载跑在后台任务里,完成时素材库要自己刷新 —— 不刷的话新素材要切走再切回来才看得见
        // (配音那条路正是这么被报上来的)。
        onQueued={() => void qc.invalidateQueries({ queryKey: assetKeys.everywhere() })}
      />

      {assets.isPending ? <MediaLibrarySkeleton list={display === "list"} /> : assets.isError ? <EmptyState icon={<FolderOpen />} title={t("pageLoadError")} body={assets.error.message} action={<Button variant="secondary" onClick={() => void assets.refetch()}>{t("retry")}</Button>} /> : libraryEmpty ? (
        <EmptyState
          icon={<FolderOpen size={22} />}
          title={t("mediaEmptyTitle")}
          body={t("mediaEmptyBody")}

        />
      ) : visible.length === 0 ? <EmptyState icon={<FolderOpen />} title={t("studioNoMatches")} body={t("studioNoMatchesHint")} /> : (
        //: 只画看得见的那几行(加上下各一段缓冲),其余的用留白占着高度 —— 滚动条说的还是整份清单(见 useVirtualRows)。
        //: 网格一行几张按网格的宽度算,和此前 `repeat(auto-fill, minmax(220px, 1fr))` 同一条规则。
        <div ref={attachRows} data-media-rows className="py-6">
          {virtual.padTop > 0 && <div data-pad-top aria-hidden="true" style={{ height: virtual.padTop }} />}
          {rows.slice(virtual.start, virtual.end).map((row, offset) => {
            const key = rowKeys[virtual.start + offset];
            return display === "grid" ? (
              <div key={key} ref={virtual.measure(key)} className="grid gap-x-6 pb-7" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
                {row.map(renderAsset)}
              </div>
            ) : (
              <div key={key} ref={virtual.measure(key)} className="border-b border-divider">
                {row.map(renderAsset)}
              </div>
            );
          })}
          <div data-pad-bottom aria-hidden="true" style={{ height: virtual.padBottom }} />
        </div>
      )}
      {assets.isFetchingNextPage && (
        <div role="status" className="grid place-items-center py-4 text-muted-foreground">
          <Loader2 size={16} className="animate-mosael-spin" />
          <span className="sr-only">{t("pageLoading")}</span>
        </div>
      )}

      <AssetPreviewModalById id={previewingId} onClose={closePreview} actions={detailActions} />
      <SetAsReferenceDialog asset={referencing} onClose={() => setReferencing(null)} />
      {denoiseDialog}
      <RenameDialog
        open={renaming !== null}
        title={t("renameAsset")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        pending={rename.isPending}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <TagsDialog
        open={editingTags !== null}
        title={t("editTags")}
        initialTags={editingTags ? tagsOf(editingTags) : []}
        onCancel={() => setEditingTags(null)}
        onSubmit={(tags) => editingTags && saveTags.mutate({ id: editingTags.id, tags })}
      />
      <TagsDialog
        open={batchTagging}
        title={t("addTags")}
        body={t("addTagsBody")}
        initialTags={[]}
        onCancel={() => setBatchTagging(false)}
        onSubmit={(tags) => tags.length > 0 && batchAddTags.mutate(tags)}
      />
      <ConfirmDialog
        open={deleting !== null || (deleteError !== null && !batchDeleting)}
        title={t("deleteConfirmTitle")}
        body={deleteError ?? t("deleteAssetBody")}
        onCancel={() => {
          setDeleting(null);
          setDeleteError(null);
        }}
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
          else setDeleteError(null);
        }}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("deleteAssetsBody").replace("{n}", String(selectedIds.size))}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate()}
      />
      {comparing && comparable.length >= 2 && compared.length === comparable.length && (compareKind === "video" ? (
        <VideoCompareView assets={compared} onClose={() => setComparing(false)} />
      ) : (
        <AssetCompareView assets={compared} onClose={() => setComparing(false)} />
      ))}
      </div>
    </div>
  );
}

function AssetTile({ asset, selected = false, list = false }: { asset: AssetCard; selected?: boolean; list?: boolean }) {
  const t = useI18n();
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const { duration, width, height, fps } = asset.media_info;
  //: 文档的封面是解析时渲的第一页(ADR 0031),还没有就画图标。
  const hasThumb = asset.kind !== "audio" && (asset.kind !== "document" || Boolean(asset.media_info.has_thumbnail)) && !thumbFailed;
  return (
    <article
      className={cn(
        "cursor-pointer rounded-lg transition-colors",
        list ? "-mx-3 flex items-center gap-5 px-3 py-4 pr-12 hover:bg-secondary/40" : "grid gap-3",
        //: 选中:卡片描一圈主色;**列表行铺一层淡主色底,不描边** —— 连着选几行时,一圈圈描边
        //: 叠在一起(上一行的下沿压着下一行的上沿)很乱,底色连成一片才读得出「这几行选中了」。
        selected && !list && "border-primary shadow-[0_0_0_1px_var(--primary)]",
        selected && list && "bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--primary)_11%,transparent)]",
      )}
    >
      <div className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-panel-inset text-muted-foreground", list ? "h-20 w-32" : "aspect-video")}>
        {hasThumb ? (
          <img
            src={assetThumbnailUrl(asset.id)}
            alt=""
            loading="lazy"
            decoding="async"
            className={cn("absolute inset-0 h-full w-full", asset.kind === "image" ? "object-contain" : "object-cover")}
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span>{kindIcon(asset.kind)}</span>
        )}
        {/* 时长角标只对有时基的素材(视频/音频)有意义;图片 duration 恒为 0,别显示 00:00。 */}
        {asset.kind !== "image" && duration != null && (
          <span className="absolute bottom-1.5 right-1.5 rounded-sm bg-[rgba(10,12,15,0.75)] px-[5px] py-px font-mono text-ui-xs tabular-nums text-[#e8eaed]">
            {formatTimecode(duration)}
          </span>
        )}
        {/* 标签叠在缩略图左下角(而非信息区),这样有无标签的卡片信息区一样高、栅格不错位。 */}
        <TagChips tags={tagsOf(asset)} tone="overlay" className="absolute bottom-1.5 left-1.5 max-w-[70%] flex-wrap" />
      </div>
      <div className="grid min-w-0 flex-1 gap-1.5 px-0.5">
        {/* relative z-[2]:浮在整卡那颗透明按钮上面,被截断时悬停看得到全文(点击照样冒泡到卡片)。 */}
        <Truncate as="strong" className="relative z-[2] text-ui-md font-semibold">
          {asset.name}
        </Truncate>
        <div className="flex items-center gap-1.5">
          <span className="text-ui-xs text-muted-foreground">{t(assetKindKey(asset.kind))}</span>
          <small className="text-ui-xs text-muted-foreground">
            {t(assetOriginKey(asset))}
            {showsContainsAi(asset) ? ` · ${t("mediaSourceContainsAi")}` : ""}
          </small>
        </div>
        {/* 逐句配音的一句名字都一样(「某某音色 · 配音」):认得出它的是念的那句话,写在尺寸那一行的位置上。 */}
        {asset.media_info.line_text ? (
          <Truncate className="text-ui-xs text-muted-foreground">{asset.media_info.line_text}</Truncate>
        ) : (
          <Truncate className="font-mono text-ui-xs tabular-nums text-muted-foreground">
            {asset.kind === "document" ? documentFacts(asset) : width ? `${width}×${height}` : "—"}
            {asset.kind === "video" && fps ? ` · ${Math.round(fps)}fps` : ""}
            {asset.created_at ? ` · ${formatShortDate(asset.created_at)}` : ""}
          </Truncate>
        )}
      </div>
    </article>
  );
}

/**
 * 素材还没拉回来时,按**当前的展示方式**先把卡片/行的骨架摆出来。
 *
 * 此前是页面正中一个转圈:素材一到,版面从一个圈跳成满屏的卡片。骨架和 AssetTile 同一套
 * 尺寸(卡片 16:9 缩略图 + 两行字;列表 128×80 缩略图 + 三行字),到了原地换掉,不跳。
 */
function MediaLibrarySkeleton({ list }: { list: boolean }) {
  const t = useI18n();
  return (
    <div
      role="status"
      aria-busy="true"
      className={cn("py-6", list ? "grid divide-y divide-divider" : "grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-7")}
    >
      <span className="sr-only">{t("pageLoading")}</span>
      {Array.from({ length: list ? 6 : 8 }, (_, index) =>
        list ? (
          <div key={index} className="-mx-3 flex items-center gap-5 px-3 py-4" aria-hidden="true">
            <Skeleton className="h-20 w-32 shrink-0 rounded-lg" />
            <div className="grid min-w-0 flex-1 gap-2">
              <Skeleton className="h-4 w-2/5" />
              <Skeleton className="h-3 w-1/4" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ) : (
          <div key={index} className="grid gap-3" aria-hidden="true">
            <Skeleton className="aspect-video w-full rounded-lg" />
            <div className="grid gap-2 px-0.5">
              <Skeleton className="h-4 w-3/5" />
              <Skeleton className="h-3 w-2/5" />
            </div>
          </div>
        ),
      )}
    </div>
  );
}

function kindIcon(kind: string) {
  if (kind === "audio") return <FileAudio size={22} />;
  if (kind === "image") return <FileImage size={22} />;
  if (kind === "document") return <FileText size={22} />;
  return <FileVideo size={22} />;
}

