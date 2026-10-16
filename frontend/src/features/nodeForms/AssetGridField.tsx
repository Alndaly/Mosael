import React from "react";
import { closestCenter, DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, rectSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Image as ImageIcon, ImageOff, Plus, RotateCcw, Upload, Wand2, X } from "lucide-react";

import { assetThumbnailUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useDndAccessibility } from "@/components/app/dndAccessibility";
import { AssetGridPicker, type GridAsset } from "@/components/app/AssetGridPicker";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
import { acceptFor, AssetUploadStatus, fileKind, namedFile, useAssetUpload, wrongKindText } from "@/components/generation/assetUpload";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { parseIds } from "@/features/nodeForms/ScenePropsField";
import { useAssetDetails, useAssetSearch } from "@/lib/assetQueries";
import { useFileDrop } from "@/lib/useFileDrop";
import { cn } from "@/lib/utils";

/**
 * 「要模型看的图片」:紧凑的图片格子(大模型节点的 `image_asset_ids`,后端声明点名 `editor: "asset_grid"`)。
 *
 * 值是一串逗号分隔的素材 id(后端 `id_list` 收逗号分隔串或真列表;接上游时是 `{{上游}}` 引用,那半边
 * 由外层裹 —— 这里只管「手动」:挑、排序、传)。**顺序就是发给模型的顺序**:格子整格是拖柄
 * (dnd-kit sortable),拖完把新顺序写回值。
 *
 * - 四列、每格 h-12(48px):缩略图 `object-cover` 填满;悬停露右上角 × 移除。
 * - 末尾永远跟两格虚线格:**上传**(点 ⬆️ 选文件;把文件拖到字段上也传,一次传一个,多文件排队串行)
 * 和**素材库**(点 ＋ 开 `AssetGridPicker` 多选,角标标先后,footer 确认)。满 8 张两格消失。
 * - 进度不占格子:格子下面一行 `text-ui-2xs` —— 在传第几个/共几个、失败给重试/取消。
 * - 被删的素材(详情查不到、缩略图也 404)画占位图标,悬停说它已不在素材库里。
 * - **自动来的那几处引用**(`refs`,见 workflows/referencedImages):提示词里引用了图片素材时,后端运行时
 *   会把那几张图并进这一格(「引用即发送」)。它们和手动挑的**分开摆**在下面一行 —— 名字是引用
 *   (「画图 · 素材」),来源看得见;× 去掉一处 = 写进 `<字段>_excluded`,运行时的取图认它(去掉就是去掉,
 *   下一轮不会又塞回来),点回来即可恢复。
 */

/** 一格 / 虚线操作格共用的骨架;高 48px 是内容不是控件(docs/DESIGN_LANGUAGE.md)。 */
const TILE_CLASS = "relative h-12 overflow-hidden rounded-lg border";

/** 自动来的一处引用:给人看的名字 + 存进排除清单的记号(见 workflows/referencedImages)。 */
export interface AutoImageRef {
  /** 引用路径(`图.asset_id`)—— 排除清单里存的就是它。 */
  path: string;
  /** 给人看的名字(「画图 · 素材」)。 */
  label: string;
  /** 静态就知道是哪张素材时给出来;用来判它到底是不是图片(不是图片的不会被发给模型)。 */
  assetId: string | null;
}

export function AssetGridField({
  value,
  workspaceId,
  max = 8,
  refs = [],
  excluded = [],
  onExcludedChange,
  onChange,
}: {
  /** 逗号分隔的素材 id 串(也收真列表:值可能来自上游插值)。 */
  value: unknown;
  workspaceId: string;
  /** 最多几张(发给模型的上限);满了上传格、素材库格就不出现。 */
  max?: number;
  /** 提示词里引用到的图(运行时自动带上)。空 = 这一格没有自动来的,整块不出现。 */
  refs?: readonly AutoImageRef[];
  /** 已经点名不要的那几处引用(值存在 `<字段>_excluded` 那一格里)。 */
  excluded?: readonly string[];
  /** 改排除清单。不给就只能看不能改。 */
  onExcludedChange?: (next: string[]) => void;
  onChange: (next: string) => void;
}) {
  const t = useI18n();
  const picked = React.useMemo(
    () => (Array.isArray(value) ? value.map(String) : parseIds(String(value ?? ""))).filter(Boolean),
    [value],
  );
  const details = useAssetDetails(picked);
  //: 自动来的那几处引用里,静态就知道是哪张素材的(源节点是「素材」且写死了 id):查一下它的种类 ——
  //: 不是图片的那些运行时会被跳过,界面上明说「不是图片,不会发送」,而不是让人等一个空的结果。
  const autoAssetIds = React.useMemo(
    () => refs.map((one) => one.assetId).filter((id): id is string => Boolean(id)),
    [refs],
  );
  const autoDetails = useAssetDetails(autoAssetIds);

  /** 排好序的新 id 串写回值;空就是空串(不是 "[]")。 */
  const write = (next: string[]) => onChange(next.join(","));

  //: upload 的 done 回调闭包要读到最新的 picked(传的间隙里值可能已变):render 时把最新值塞进 ref。
  const pickedRef = React.useRef(picked);
  pickedRef.current = picked;

  const append = React.useCallback(
    (id: string) => {
      //: 传的间隙里又挑了几张、满了:传完的那张留在素材库里,不硬塞进来。
      const current = pickedRef.current;
      if (current.length < max) onChange([...current, id].join(","));
    },
    [max, onChange],
  );

  //: 一次只传一个(useAssetUpload 的规矩),多文件排队:传完一个 done 再传下一个。
  const upload = useAssetUpload(workspaceId);
  const queueRef = React.useRef<File[]>([]);
  const [batch, setBatch] = React.useState({ total: 0, done: 0 });

  const pump = React.useCallback(() => {
    const next = queueRef.current.shift();
    if (!next) return;
    upload.start(namedFile(next), (asset: Asset) => {
      append(asset.id);
      setBatch((batch) => ({ ...batch, done: batch.done + 1 }));
      pump();
    });
  }, [upload, append]);

  const take = React.useCallback(
    (files: File[]) => {
      const images = files.filter((file) => fileKind(file) === "image");
      if (!images.length) {
        if (files[0]) upload.reject(wrongKindText(t, files[0], "image"));
        return;
      }
      const room = max - pickedRef.current.length - queueRef.current.length - (upload.state.status === "uploading" ? 1 : 0);
      if (room <= 0) {
        upload.reject(t("wfAssetGridMax").replace("{max}", String(max)));
        return;
      }
      queueRef.current.push(...images.slice(0, Math.max(room, 0)));
      setBatch((batch) => ({ total: batch.total + Math.min(images.length, Math.max(room, 0)), done: batch.done }));
      pump();
    },
    [max, upload, pump, t],
  );

  /** 没传上/传完了:把排队和计数清掉(「取消」和「知道了」都走这里)。 */
  const clearQueue = React.useCallback(() => {
    queueRef.current = [];
    setBatch({ total: 0, done: 0 });
  }, []);
  const cancelUpload = React.useCallback(() => {
    upload.cancel();
    clearQueue();
  }, [upload, clearQueue]);
  const dismiss = React.useCallback(() => {
    upload.dismiss();
    clearQueue();
  }, [upload, clearQueue]);

  const drop = useFileDrop(take);
  const chooser = React.useRef<HTMLInputElement | null>(null);
  const [picking, setPicking] = React.useState(false);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const dndAccessibility = useDndAccessibility();
  const onDragEnd = (event: DragEndEvent) => {
    const over = event.over ? String(event.over.id) : null;
    if (!over) return;
    const from = picked.indexOf(String(event.active.id));
    const to = picked.indexOf(over);
    if (from < 0 || to < 0 || from === to) return;
    write(arrayMove(picked, from, to));
  };

  const full = picked.length >= max;
  return (
    <div className="relative" data-asset-grid="" {...drop.handlers}>
      <DndContext
        sensors={sensors}
        accessibility={dndAccessibility}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext items={picked} strategy={rectSortingStrategy}>
          <div className="grid grid-cols-4 gap-1">
            {picked.map((id, index) => (
              <PickedTile
                key={id}
                id={id}
                index={index}
                asset={details.byId.get(id)}
                settled={details.settled}
                onRemove={() => write(picked.filter((_, at) => at !== index))}
              />
            ))}
            {/* 满 max 张:两格虚线格消失,格子就此定死(先移除再改)。 */}
            {!full && (
              <>
                {/* 虚线格的外壳是格子(高、圆角是内容的,不是控件的);整格可点的部分走 IconButton,名字只写一次。 */}
                <div className={cn(TILE_CLASS, "border-dashed bg-muted/40 text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground")}>
                  <IconButton
                    unstyled
                    data-upload-tile=""
                    label={t("wfAssetGridUpload")}
                    onClick={() => chooser.current?.click()}
                    className="grid size-full cursor-pointer place-items-center"
                  >
                    <Upload size={16} strokeWidth={1.8} />
                  </IconButton>
                </div>
                <div className={cn(TILE_CLASS, "border-dashed bg-muted/40 text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground")}>
                  <IconButton
                    unstyled
                    data-add-tile=""
                    label={t("wfAssetGridAdd")}
                    onClick={() => setPicking(true)}
                    className="grid size-full cursor-pointer place-items-center"
                  >
                    <Plus size={16} strokeWidth={1.8} />
                  </IconButton>
                </div>
              </>
            )}
          </div>
        </SortableContext>
      </DndContext>

      {/* 进度不占格子:下面一行小字。在传第 i 个 / 共 n 个;失败给重试/取消;收不了说为什么。 */}
      {upload.state.status === "uploading" && (
        <div role="status" data-asset-grid-upload="uploading" className="mt-1 flex min-w-0 items-center gap-1.5 text-ui-2xs text-muted-foreground">
          <Truncate className="min-w-0 flex-1">
            {t("wfAssetGridUploading")
              .replace("{name}", upload.state.name)
              .replace("{i}", String(Math.min(batch.done + 1, batch.total)))
              .replace("{n}", String(batch.total))}
          </Truncate>
          <IconButton
            size="icon-xs"
            variant="ghost"
            label={t("assetUploadCancel")}
            onClick={cancelUpload}
            className="shrink-0 text-muted-foreground"
          >
            <X size={11} />
          </IconButton>
        </div>
      )}
      {/* 没传上 / 收不了:那一句走 FailureCard 一行档(棘轮:design/failureDisplays.test.ts);重试、关掉摆在同行 —— */}
      {/* FailureCard 的 actions 收在「详情」浮层里,这种一行 alert 的地方要直接点得到(和 boards AssetUploadStatus 同一摆法)。 */}
      {(upload.state.status === "failed" || upload.state.status === "rejected") && (
        <div role="alert" data-asset-grid-upload={upload.state.status} className="mt-1 flex min-w-0 items-center gap-1 text-ui-2xs">
          <FailureCard
            size="inline"
            className="min-w-0 flex-1"
            title={upload.state.status === "failed" ? t("assetUploadFailedTitle") : t("assetUploadRejectedTitle")}
            {...rawFailureFields(
              upload.state.status === "failed"
                ? t("assetUploadFailed").replace("{name}", upload.state.name).replace("{reason}", upload.state.reason)
                : upload.state.message,
              upload.state.status === "failed" ? t("assetUploadFailedTitle") : t("assetUploadRejectedTitle"),
            )}
          />
          {upload.state.status === "failed" && (
            <Button size="xs" variant="ghost" data-upload-retry="" className="shrink-0 gap-1" onClick={upload.retry}>
              <RotateCcw size={11} />
              {t("retry")}
            </Button>
          )}
          <IconButton
            size="icon-xs"
            variant="ghost"
            label={t("close")}
            onClick={dismiss}
            className="shrink-0 text-muted-foreground"
          >
            <X size={11} />
          </IconButton>
        </div>
      )}

      {/* **自动来的那几处引用**(「引用即发送」):提示词 / 系统提示词里 `{{…}}` 引用到的图片素材,运行时会
          自动和提示词一起发给模型(后端 binding.with_referenced_assets —— 同一份规则,这里只是把来源摆出来)。
          和上面手动挑的缩略图**分开**摆:看着名字就知道模型为什么会看到它,不用去翻提示词。
          × 去掉一处 = 写进 `<字段>_excluded`,运行时的取图认它;点回来即可恢复(不是删了就回不来)。 */}
      {refs.length > 0 && (
        <div className="mt-1.5 grid gap-1" data-auto-images="">
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            <span className="inline-flex shrink-0 items-center gap-1 text-ui-2xs font-medium text-muted-foreground">
              <Wand2 size={11} strokeWidth={1.8} />
              {t("wfAssetGridAutoTitle")}
            </span>
            {refs.map((ref) => {
              const on = !excluded.includes(ref.path);
              //: 静态就知道是哪张素材时,顺手判一眼它是不是图片 —— 不是的那些运行时会被跳过。
              const asset = ref.assetId ? autoDetails.byId.get(ref.assetId) : undefined;
              const notImage = asset !== undefined && asset.kind !== "image";
              return (
                <span
                  key={ref.path}
                  data-auto-image-ref={ref.path}
                  data-auto-image-on={on ? "true" : "false"}
                  className={cn(
                    "inline-flex min-w-0 items-center gap-1 rounded-full border py-px pl-2 pr-0.5 text-ui-2xs",
                    on ? "border-border bg-muted/40 text-foreground" : "border-dashed border-border text-muted-foreground",
                  )}
                >
                  <Truncate className="max-w-[9rem]" as="span">
                    {ref.label}
                  </Truncate>
                  {on && notImage && (
                    <span data-auto-image-skipped="" className="shrink-0 text-muted-foreground">
                      {t("wfAssetGridAutoNotImage")}
                    </span>
                  )}
                  <IconButton
                    size="icon-xs"
                    variant="ghost"
                    data-auto-image-toggle=""
                    label={(on ? t("wfAssetGridAutoDrop") : t("wfAssetGridAutoRestore")).replace("{name}", ref.label)}
                    onClick={() =>
                      onExcludedChange?.(
                        on ? [...excluded, ref.path] : excluded.filter((one) => one !== ref.path),
                      )
                    }
                    className="shrink-0 text-muted-foreground"
                  >
                    {on ? <X size={11} /> : <RotateCcw size={11} />}
                  </IconButton>
                </span>
              );
            })}
          </div>
          {/* 到顶了说清:自动来的也要占那 8 个位置,不然用户只会看到运行时一句「最多 8 张」。 */}
          {picked.length + refs.filter((one) => !excluded.includes(one.path)).length > max && (
            <p role="alert" data-auto-images-over="" className="text-ui-2xs text-destructive">
              {t("wfAssetGridAutoTooMany").replace("{max}", String(max))}
            </p>
          )}
          <p className="text-ui-2xs leading-[1.5] text-muted-foreground">{t("wfAssetGridAutoHint")}</p>
        </div>
      )}

      {/* 把文件拖到字段上任何一处都算数(不是某一个方框)。 */}
      {drop.active && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg border border-dashed border-primary bg-[color-mix(in_oklab,var(--primary)_8%,var(--background))]">
          <span className="inline-flex items-center gap-1.5 text-ui-2xs font-medium text-primary">
            <Upload size={12} />
            {t("boardsUploadDropHint")}
          </span>
        </div>
      )}

      <input
        ref={chooser}
        type="file"
        accept={acceptFor("image")}
        multiple
        hidden
        data-asset-grid-chooser=""
        onChange={(event) => {
          take(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />

      {picking && (
        <AssetGridDialog
          workspaceId={workspaceId}
          initial={picked}
          max={max}
          upload={upload}
          onClose={() => setPicking(false)}
          onConfirm={(ids) => {
            write(ids);
            setPicking(false);
          }}
        />
      )}
    </div>
  );
}

/** 一张已挑的图:缩略图填满整格;悬停露右上角 ×;整格是拖柄。 */
function PickedTile({
  id,
  index,
  asset,
  settled,
  onRemove,
}: {
  id: string;
  index: number;
  asset: Asset | undefined;
  settled: boolean;
  onRemove: () => void;
}) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const [imgFailed, setImgFailed] = React.useState(false);
  //: 详情查得到 → 名字是它的;查不到(可能还没回来) → 先写 id。都 settled 了还没有 = 被删了。
  const missing = settled && !asset;
  const failed = missing || imgFailed;
  const name = asset?.name || asset?.original_filename || id;
  return (
    <Hint label={missing ? t("wfAssetGridMissing") : name}>
      <div
        ref={setNodeRef}
        style={{ transform: CSS.Transform.toString(transform), transition }}
        {...attributes}
        {...listeners}
        data-asset-tile={id}
        data-dragging={isDragging}
        aria-label={missing ? `${name} · ${t("wfAssetGridMissing")}` : `${t("wfAssetGridImage")} ${index + 1}: ${name}`}
        className={cn(
          TILE_CLASS,
          "group cursor-grab touch-none border-border bg-panel-inset text-muted-foreground active:cursor-grabbing",
          isDragging && "z-20 opacity-70",
        )}
      >
        {failed ? (
          <span className="grid size-full place-items-center">
            <ImageOff size={14} strokeWidth={1.6} />
          </span>
        ) : (
          <img
            src={assetThumbnailUrl(id)}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            onError={() => setImgFailed(true)}
            className="absolute inset-0 size-full object-cover"
          />
        )}
        <IconButton
          unstyled
          label={t("wfAssetGridRemove").replace("{n}", String(index + 1))}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={onRemove}
          className="absolute right-0.5 top-0.5 z-10 grid size-5 cursor-pointer place-items-center rounded-full bg-[rgba(10,12,15,0.72)] text-[#e8eaed] opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <X size={12} />
        </IconButton>
      </div>
    </Hint>
  );
}

/**
 * 素材库挑图弹窗(`AssetGridPicker` 的又一种用法:多选、先选再确认)。只列图片;选中的格子角标标
 * 先后 —— 挑的顺序就是发给模型的顺序。上限 max:到顶再点没选中的格子不添(描述里写着上限)。
 * 打开时从当前值起选,确认把整份选择(按挑的顺序)写回 —— 所以在弹窗里也能去掉已挑的图。
 */
function AssetGridDialog({
  workspaceId,
  initial,
  max,
  upload,
  onClose,
  onConfirm,
}: {
  workspaceId: string;
  initial: string[];
  max: number;
  upload: ReturnType<typeof useAssetUpload>;
  onClose: () => void;
  onConfirm: (ids: string[]) => void;
}) {
  const t = useI18n();
  const [chosen, setChosen] = React.useState(initial);
  const [justUploaded, setJustUploaded] = React.useState<string[]>([]);

  //: 整个素材库只列图片;搜索、翻页交给 useAssetSearch(和画板挑素材同一套)。
  const library = useAssetSearch({ workspace_id: workspaceId, kind: ["image"] }, { enabled: true });

  const chooser = React.useRef<HTMLInputElement | null>(null);
  //: 弹窗里传的,传完直接算「挑中了」—— 不用等素材库刷新完再让人找它。
  const take = (files: File[]) => {
    const image = files.find((file) => fileKind(file) === "image");
    if (!image) {
      if (files[0]) upload.reject(wrongKindText(t, files[0], "image"));
      return;
    }
    upload.start(namedFile(image), (asset: Asset) => setJustUploaded((ids) => [...ids, asset.id]));
  };
  const drop = useFileDrop(take);

  const items: readonly GridAsset[] = library.items;
  const narrowed = library.text.trim() !== "";
  //: 刚在弹窗里传完的那几张算「挑中了」,跟在已挑的后面(和挑的顺序一致,先挑的在前)。
  const all = [...chosen, ...justUploaded.filter((id) => !chosen.includes(id))];
  const toggle = (asset: GridAsset) => {
    setChosen((current) => {
      if (current.includes(asset.id)) return current.filter((id) => id !== asset.id);
      //: 到顶再点没选中的:不添(也不把已选的踢掉)。
      if (current.length >= max) return current;
      return [...current, asset.id];
    });
  };

  return (
    <AssetGridPicker
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("wfAssetGridPickTitle")}
      description={t("wfAssetGridPickDesc").replace("{max}", String(max))}
      searchLabel={t("boardsSearchImages")}
      query={library.text}
      onQueryChange={library.search}
      toolbar={
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => chooser.current?.click()}>
          <Upload />
          {t("wfAssetGridUpload")}
        </Button>
      }
      banner={<AssetUploadStatus upload={upload} />}
      dropzone={{
        handlers: drop.handlers,
        overlay: drop.active ? (
          <div className="pointer-events-none absolute inset-0 z-30 grid rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_8%,var(--background))] p-4">
            <div className="grid place-items-center rounded-lg border-2 border-dashed border-primary/70">
              <span className="inline-flex items-center gap-2 text-ui-sm font-semibold text-primary">
                <Upload size={16} />
                {t("boardsUploadDropHint")}
              </span>
            </div>
          </div>
        ) : null,
      }}
      items={items}
      onActivate={toggle}
      selection={{
        multiple: true,
        isSelected: (asset) => all.includes(asset.id),
        //: 没选中的给 -1:角标画的是 order + 1,-1 不画(见 AssetGridPicker 的格子)。
        order: (asset) => all.indexOf(asset.id),
      }}
      pending={library.isLoading}
      error={library.isError ? library.error.message : null}
      onRetry={() => void library.refetch()}
      onReachEnd={library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
      loadingMore={library.isFetchingNextPage}
      empty={
        narrowed
          ? { icon: null, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
          : { icon: <ImageIcon />, title: t("boardsNoImages"), body: t("boardsPickEmptyHint") }
      }
      footer={
        <div className="flex min-w-0 items-center gap-2">
          <Truncate className="min-w-0 flex-1 text-ui-xs text-muted-foreground">
            {t("wfAssetGridPickedCount").replace("{n}", String(all.length)).replace("{max}", String(max))}
          </Truncate>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            data-asset-grid-confirm=""
            onClick={() => onConfirm(all)}
          >
            {t("wfAssetGridConfirm").replace("{n}", String(all.length))}
          </Button>
        </div>
      }
    />
  );
}
