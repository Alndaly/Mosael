import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, rectSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  Film,
  FolderOpen,
  ImagePlus,
  Loader2,
  MoreHorizontal,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { DrawMenu } from "@/features/entities/DrawDialog";
import { isImeKeystroke } from "@/lib/shortcuts";

import { assetKeys } from "@/api/queryKeys";
import {
  addEntityReference,
  assetFileUrl,
  assetPreviewUrl,
  assetThumbnailUrl,
  entityKeys,
  importAsset,
  removeEntityReference,
  reorderEntityReferences,
  setEntityReferenceRole,
  updateEntity,
  type Entity,
  type EntityReference,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverClose, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useFileDrop } from "@/lib/useFileDrop";
import { importEach, importFailureText } from "@/lib/importEach";
import { cn } from "@/lib/utils";
import { useCatalogLabels } from "@/features/entities/entityMeta";
import { LibraryPickerDialog } from "@/features/entities/LibraryPickerDialog";

const WALL_ID = "entity-wall";

/** 参考图能收的素材:图片和视频(一段转身的视频也是参考)。 */
function referable(file: File): boolean {
  return /^(image|video)\//.test(file.type);
}

/**
 * 参考图墙:每张标着角度(正面 / 侧面 / 三视图……)。
 *
 * - 拖着排先后(dnd-kit);菜单里也有「前移 / 后移」,键盘和读屏够得着;
 * - 从素材库挑:弹窗里搜、多选,一次挂好几张;也能直接上传;
 * - 把文件拖到墙上:先导进素材库,再挂成参考图(参考图**就是**素材库里的素材,不另存一份);
 * - 换角度、设封面、移出(素材本身不动)。
 */
/** 一面参考图墙在灯箱里的样子:按墙上的先后,图是图、视频就地播放。墙上点开和资产封面点开用的是同一组。 */
export function referenceGallery(refs: readonly Pick<EntityReference, "asset_id" | "asset_kind" | "asset_name">[]): ImagePreviewItem[] {
  return refs.map((ref) => ({
    src: ref.asset_kind === "image" ? assetPreviewUrl(ref.asset_id) : assetFileUrl(ref.asset_id),
    title: ref.asset_name,
    video: ref.asset_kind !== "image",
  }));
}

export function ReferenceWall({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [order, setOrder] = React.useState<string[]>(() => entity.references.map((one) => one.asset_id));
  React.useEffect(() => setOrder(entity.references.map((one) => one.asset_id)), [entity.references]);
  const byId = new Map(entity.references.map((one) => [one.asset_id, one]));
  const refs = order.map((id) => byId.get(id)).filter((one): one is EntityReference => Boolean(one));
  const { openImagePreview } = useImagePreview();
  //: 点一张放大看;灯箱里左右翻的是这一面墙上的全部(按墙上的先后),视频就地播放。
  const gallery = referenceGallery(refs);
  const preview = (index: number) => openImagePreview({ ...gallery[index], gallery });

  const settle = (next: Entity) => {
    qc.setQueryData(entityKeys.detail(workspaceId, entity.id), next);
    void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
  };
  const fail = (error: unknown) => toast.error(errorText(error));
  //: 一批挂到一半失败时,前面几张其实已经挂上了:重新取一遍这个资产,墙上照实显示(不然要刷新页面才看得到)。
  const refetch = () => void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });

  const [picking, setPicking] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement | null>(null);
  const add = useMutation({
    //: 一张一张挂:接口一次收一张;挂的先后就是挑的先后,落在墙的末尾。
    mutationFn: async (assetIds: string[]) => {
      let last: Entity | null = null;
      for (const assetId of assetIds) last = await addEntityReference(entity.id, { asset_id: assetId });
      return last;
    },
    onSuccess: (next) => {
      setPicking(false);
      if (next) settle(next);
    },
    onError: (error) => {
      refetch();
      fail(error);
    },
  });
  const role = useMutation({
    mutationFn: ({ assetId, next }: { assetId: string; next: string }) => setEntityReferenceRole(entity.id, assetId, next),
    onSuccess: settle,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (assetId: string) => removeEntityReference(entity.id, assetId),
    onSuccess: settle,
    onError: fail,
  });
  const cover = useMutation({
    mutationFn: (assetId: string) => updateEntity(entity.id, { cover_asset_id: assetId }),
    onSuccess: settle,
    onError: fail,
  });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => reorderEntityReferences(entity.id, ids),
    onSuccess: settle,
    onError: (error) => {
      setOrder(entity.references.map((one) => one.asset_id));
      fail(error);
    },
  });
  //: 逐个传、一个失败不拦后面的(lib/importEach,和素材库的导入同一条):进了库的素材库照样刷新、挂上的墙上照样显示,
  //: 没进来的最后一并说。
  const upload = useMutation({
    mutationFn: (files: File[]) =>
      importEach(files, async (file) => {
        const asset = await importAsset({ workspaceId, file });
        return addEntityReference(entity.id, { asset_id: asset.id });
      }),
    onSuccess: ({ imported, failed }) => {
      //: 失败的那一个可能已经进了素材库、只是没挂上 —— 素材库和这个资产都照实刷新(settle 里也会重取)。
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      const last = imported[imported.length - 1];
      if (last) settle(last);
      else refetch();
      const partial = importFailureText(t, imported.length, failed);
      if (partial) toast.error(partial);
    },
  });
  const drop = useFileDrop((files) => upload.mutate(files), referable);

  const move = (assetId: string, offset: number) => {
    const from = order.indexOf(assetId);
    const to = from + offset;
    if (from < 0 || to < 0 || to >= order.length) return;
    const next = arrayMove(order, from, to);
    setOrder(next);
    reorder.mutate(next);
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const onDragEnd = (event: DragEndEvent) => {
    const active = String(event.active.id);
    const over = event.over ? String(event.over.id) : null;
    if (!over) return;
    if (over === WALL_ID || active === over) return;
    const from = order.indexOf(active);
    const to = order.indexOf(over);
    if (from < 0 || to < 0) return;
    const next = arrayMove(order, from, to);
    setOrder(next);
    reorder.mutate(next);
  };

  const busy = drop.active || upload.isPending;
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <section className="grid min-w-0 content-start gap-4" aria-label={t("entityReferences")} data-reference-wall="">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="grid min-w-0 gap-0.5">
            <p className="m-0 text-ui-sm text-muted-foreground">{t("entityReferencesHint")}</p>
            {labels.priorityFor(entity.kind).length > 0 && (
              <p className="m-0 text-ui-xs text-muted-foreground" data-attach-order="">
                {t("entityAttachOrder").replace("{order}", labels.priorityFor(entity.kind).join(" > "))}
              </p>
            )}
          </div>
          <span className="flex flex-wrap gap-2">
            {/* 照现有的图再画几张同一个:一张图片参考都没有时画不出「同一个」,先传一张。 */}
            <DrawMenu entity={entity} workspaceId={workspaceId} disabled={!refs.some((one) => one.asset_kind === "image")} />
            <Button variant="outline" onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
              <Upload />
              {t("entityUpload")}
            </Button>
            <Button onClick={() => setPicking(true)}>
              <FolderOpen />
              {t("entityFromLibrary")}
            </Button>
          </span>
          <input
            ref={fileInput}
            type="file"
            accept="image/*,video/*"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []).filter(referable);
              event.currentTarget.value = "";
              if (files.length) upload.mutate(files);
            }}
          />
        </div>
        <Wall active={busy} empty={refs.length === 0} handlers={drop.handlers}>
          {busy && (
            <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-xl bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
              <span className="flex items-center gap-2 text-ui-sm font-semibold text-primary">
                {upload.isPending ? <Loader2 size={16} className="animate-mosael-spin" /> : <Upload size={16} />}
                {t(upload.isPending ? "entityImporting" : "entityDropToImport")}
              </span>
            </div>
          )}
          {refs.length === 0 ? (
            <div className="col-span-full grid justify-items-center gap-3 py-16 text-center text-muted-foreground">
              <ImagePlus size={28} strokeWidth={1.3} />
              <span className="max-w-sm text-ui-sm leading-relaxed">{t("entityReferencesEmpty")}</span>
            </div>
          ) : (
            <SortableContext items={order} strategy={rectSortingStrategy}>
              {refs.map((ref, index) => (
                <ReferenceCard
                  key={ref.asset_id}
                  reference={ref}
                  isCover={entity.display_cover_asset_id === ref.asset_id}
                  roleLabel={labels.role(ref.role)}
                  roles={labels.rolesFor(entity.kind)}
                  first={index === 0}
                  last={index === refs.length - 1}
                  onRole={(next) => role.mutate({ assetId: ref.asset_id, next })}
                  onCover={() => cover.mutate(ref.asset_id)}
                  onRemove={() => remove.mutate(ref.asset_id)}
                  onMove={(offset) => move(ref.asset_id, offset)}
                  onPreview={() => preview(index)}
                />
              ))}
            </SortableContext>
          )}
        </Wall>
      </section>
      <LibraryPickerDialog
        open={picking}
        onOpenChange={setPicking}
        workspaceId={workspaceId}
        attached={new Set(order)}
        pending={add.isPending}
        onAdd={(ids) => add.mutate(ids)}
      />
    </DndContext>
  );
}

function Wall({
  active,
  empty,
  handlers,
  children,
}: {
  active: boolean;
  empty: boolean;
  handlers: ReturnType<typeof useFileDrop>["handlers"];
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: WALL_ID });
  return (
    <div
      ref={setNodeRef}
      {...handlers}
      data-reference-drop=""
      className={cn(
        "relative grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] content-start gap-4 rounded-xl",
        //: 空着时整块是一个拖放区(虚线框);有图之后就是一面墙,不再套框 —— 框只在拖东西进来时亮出来。
        empty ? "min-h-64 border border-dashed border-border p-4" : "border border-transparent",
        (active || isOver) && "border-primary",
      )}
    >
      {children}
    </div>
  );
}

function ReferenceCard({
  reference,
  isCover,
  roleLabel,
  roles,
  first,
  last,
  onRole,
  onCover,
  onRemove,
  onMove,
  onPreview,
}: {
  reference: EntityReference;
  isCover: boolean;
  roleLabel: string;
  roles: { value: string; label: string }[];
  first: boolean;
  last: boolean;
  onRole: (next: string) => void;
  onCover: () => void;
  onRemove: () => void;
  onMove: (offset: number) => void;
  /** 放大看这一张。拖着排序不会触发它(拖动要先挪 6px,见 sensors),点角度、⋯ 也不会。 */
  onPreview: () => void;
}) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: reference.asset_id });
  const image = reference.asset_kind === "image";
  const [menuOpen, setMenuOpen] = React.useState(false);
  //: 压在图上的小控件:半透明深底、白字,在任何图上都读得清;和画板格子上的角标同一种样子。
  const overlay =
    "inline-flex items-center gap-1 rounded-md border-0 bg-[rgba(10,12,15,0.72)] text-ui-2xs font-medium text-[#e8eaed] backdrop-blur-sm";
  return (
    <figure
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-reference={reference.asset_id}
      className={cn("group m-0 grid min-w-0 gap-2", isDragging && "z-20 opacity-70")}
    >
      <div
        {...attributes}
        {...listeners}
        onClick={(event) => {
          if (!(event.target as HTMLElement).closest("button")) onPreview();
        }}
        onKeyDown={(event) => {
          listeners?.onKeyDown?.(event);
          if (event.key === "Enter" && !isImeKeystroke(event) && event.target === event.currentTarget) onPreview();
        }}
        className={cn(
          "relative grid aspect-square cursor-zoom-in place-items-center overflow-hidden rounded-lg border bg-panel-inset text-muted-foreground transition-colors",
          isCover ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : "border-border group-hover:border-border-strong",
        )}
        aria-label={`${reference.asset_name} · ${roleLabel}`}
      >
        {image ? (
          <img src={assetThumbnailUrl(reference.asset_id)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <Film size={24} strokeWidth={1.4} />
        )}
        {/* 角度就写在图上,点它就能换 —— 不再在图下面另摆一个写着同一个词的下拉。 */}
        <Popover>
          {/* 图上写的是角度的值(「正面」),它是什么悬停时说。 */}
          <Hint label={t("entityRole")}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={`${t("entityRole")}: ${reference.asset_name}`}
              aria-haspopup="menu"
              className={cn(overlay, "absolute left-2 top-2 cursor-pointer px-2 py-1 hover:bg-[rgba(10,12,15,0.88)]")}
            >
              <span data-reference-role={reference.role}>{roleLabel}</span>
              <ChevronDown size={11} className="opacity-70" />
            </button>
          </PopoverTrigger>
          </Hint>
          <MenuContent label={`${t("entityRole")}: ${reference.asset_name}`} align="start" className="max-h-72 overflow-y-auto">
            {roles.map((one) => (
              <PopoverClose asChild key={one.value}>
                <MenuItem
                  role="menuitemradio"
                  checked={one.value === reference.role}
                  label={one.label}
                  onClick={() => one.value !== reference.role && onRole(one.value)}
                />
              </PopoverClose>
            ))}
          </MenuContent>
        </Popover>
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <IconButton
              unstyled
              type="button"
              label={`${t("studioActions")}: ${reference.asset_name}`}
              aria-haspopup="menu"
              className={cn(
                overlay,
                "absolute right-2 top-2 grid size-7 cursor-pointer place-items-center p-0 transition-opacity hover:bg-[rgba(10,12,15,0.88)]",
                //: 平时收着,鼠标移上来、键盘聚焦、菜单开着时才出现 —— 一墙的图上不该顶着一排圆点。
                menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
              )}
            >
              <MoreHorizontal size={14} />
            </IconButton>
          </PopoverTrigger>
          <MenuContent label={`${t("studioActions")}: ${reference.asset_name}`} align="end">
            {image && !isCover && (
              <PopoverClose asChild>
                <MenuItem icon={<Star />} label={t("entitySetCover")} onClick={onCover} />
              </PopoverClose>
            )}
            {!first && (
              <PopoverClose asChild>
                <MenuItem icon={<ArrowLeft />} label={t("entityMoveEarlier")} onClick={() => onMove(-1)} />
              </PopoverClose>
            )}
            {!last && (
              <PopoverClose asChild>
                <MenuItem icon={<ArrowRight />} label={t("entityMoveLater")} onClick={() => onMove(1)} />
              </PopoverClose>
            )}
            <PopoverClose asChild>
              <MenuItem icon={<Trash2 />} label={t("entityRemoveReference")} destructive onClick={onRemove} />
            </PopoverClose>
          </MenuContent>
        </Popover>
        {isCover && (
          <span className="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-md bg-primary px-2 py-0.5 text-ui-2xs font-medium text-primary-foreground">
            <Star size={10} />
            {t("entityCoverBadge")}
          </span>
        )}
      </div>
      <Truncate as="figcaption" className="px-0.5 text-ui-xs text-muted-foreground">
        {reference.asset_name}
      </Truncate>
    </figure>
  );
}
