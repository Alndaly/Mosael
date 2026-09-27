import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useDraggable,
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
  Film,
  FolderOpen,
  ImagePlus,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { assetKeys } from "@/api/queryKeys";
import {
  addEntityReference,
  assetThumbnailUrl,
  entityKeys,
  importAsset,
  listAssets,
  removeEntityReference,
  reorderEntityReferences,
  setEntityReferenceRole,
  updateEntity,
  type Asset,
  type Entity,
  type EntityReference,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ACTION_MENU } from "@/components/ui/floating";
import { useFileDrop } from "@/lib/useFileDrop";
import { cn } from "@/lib/utils";
import { useCatalogLabels } from "@/features/entities/entityMeta";

/** 从素材库拖进来的那一张:dnd-kit 里的 id 带这个前缀,和墙上已有的参考图(按素材 id)分开。 */
const LIBRARY_PREFIX = "library:";
const WALL_ID = "entity-wall";

/** 参考图能收的素材:图片和视频(一段转身的视频也是参考)。 */
function referable(file: File): boolean {
  return /^(image|video)\//.test(file.type);
}

/**
 * 参考图墙:每张标着角度(正面 / 侧面 / 三视图……)。
 *
 * - 拖着排先后(dnd-kit);菜单里也有「前移 / 后移」,键盘和读屏够得着;
 * - 从素材库挑:右边那一栏,点「+」或者直接拖到墙上;
 * - 把文件拖到墙上:先导进素材库,再挂成参考图(参考图**就是**素材库里的素材,不另存一份);
 * - 换角度、设封面、移出(素材本身不动)。
 */
export function ReferenceWall({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [order, setOrder] = React.useState<string[]>(() => entity.references.map((one) => one.asset_id));
  React.useEffect(() => setOrder(entity.references.map((one) => one.asset_id)), [entity.references]);
  const byId = new Map(entity.references.map((one) => [one.asset_id, one]));
  const refs = order.map((id) => byId.get(id)).filter((one): one is EntityReference => Boolean(one));

  const settle = (next: Entity) => {
    qc.setQueryData(entityKeys.detail(workspaceId, entity.id), next);
    void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
  };
  const fail = (error: unknown) => toast.error(errorText(error));

  const add = useMutation({
    mutationFn: (assetId: string) => addEntityReference(entity.id, { asset_id: assetId }),
    onSuccess: settle,
    onError: fail,
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
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let last: Entity | null = null;
      for (const file of files) {
        const asset = await importAsset({ workspaceId, file });
        last = await addEntityReference(entity.id, { asset_id: asset.id });
      }
      return last;
    },
    onSuccess: (next) => {
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      if (next) settle(next);
    },
    onError: fail,
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
    if (active.startsWith(LIBRARY_PREFIX)) {
      add.mutate(active.slice(LIBRARY_PREFIX.length));
      return;
    }
    if (over === WALL_ID || active === over) return;
    const from = order.indexOf(active);
    const to = order.indexOf(over);
    if (from < 0 || to < 0) return;
    const next = arrayMove(order, from, to);
    setOrder(next);
    reorder.mutate(next);
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      {/* content-start:它和右边那一栏字段并排,行高跟着那一栏(字段一多就很高);不收在顶上,多出来的高度会摊进
          标题和墙之间,标题被推到半中间、空墙拉成一大片。 */}
      <section className="grid min-w-0 content-start gap-3" aria-label={t("entityReferences")} data-reference-wall="">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="grid gap-0.5">
            <h3 className="m-0 text-ui-md font-semibold">{t("entityReferences")}</h3>
            <p className="m-0 text-ui-xs text-muted-foreground">{t("entityReferencesHint")}</p>
            {labels.priority.length > 0 && (
              <p className="m-0 text-ui-xs text-muted-foreground" data-attach-order="">
                {t("entityAttachOrder").replace("{order}", labels.priority.join(" > "))}
              </p>
            )}
          </div>
          <Button variant="outline" aria-pressed={libraryOpen} onClick={() => setLibraryOpen((open) => !open)}>
            <FolderOpen />
            {t("entityFromLibrary")}
          </Button>
        </div>
        <div className={cn("grid min-w-0 content-start gap-4", libraryOpen && "2xl:grid-cols-[minmax(0,1fr)_280px]")}>
          <Wall active={drop.active || upload.isPending} handlers={drop.handlers}>
            {(drop.active || upload.isPending) && (
              <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
                <span className="flex items-center gap-2 text-ui-sm font-semibold text-primary">
                  {upload.isPending ? <Loader2 size={16} className="animate-mosael-spin" /> : <Upload size={16} />}
                  {t(upload.isPending ? "entityImporting" : "entityDropToImport")}
                </span>
              </div>
            )}
            {refs.length === 0 ? (
              <div className="col-span-full grid justify-items-center gap-2 py-10 text-center text-muted-foreground">
                <ImagePlus size={24} strokeWidth={1.4} />
                <span className="text-ui-sm">{t("entityReferencesEmpty")}</span>
              </div>
            ) : (
              <SortableContext items={order} strategy={rectSortingStrategy}>
                {refs.map((ref, index) => (
                  <ReferenceCard
                    key={ref.asset_id}
                    reference={ref}
                    isCover={entity.display_cover_asset_id === ref.asset_id}
                    roleLabel={labels.role(ref.role)}
                    roles={labels.roles}
                    first={index === 0}
                    last={index === refs.length - 1}
                    onRole={(next) => role.mutate({ assetId: ref.asset_id, next })}
                    onCover={() => cover.mutate(ref.asset_id)}
                    onRemove={() => remove.mutate(ref.asset_id)}
                    onMove={(offset) => move(ref.asset_id, offset)}
                  />
                ))}
              </SortableContext>
            )}
          </Wall>
          {libraryOpen && (
            <LibraryPanel
              workspaceId={workspaceId}
              attached={new Set(order)}
              pending={add.isPending}
              onAdd={(assetId) => add.mutate(assetId)}
            />
          )}
        </div>
      </section>
    </DndContext>
  );
}

function Wall({
  active,
  handlers,
  children,
}: {
  active: boolean;
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
        "relative grid min-h-40 grid-cols-[repeat(auto-fill,minmax(150px,1fr))] content-start gap-3 rounded-lg border border-dashed border-border p-3",
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
}) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: reference.asset_id });
  const image = reference.asset_kind === "image";
  return (
    <figure
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-reference={reference.asset_id}
      className={cn("m-0 grid min-w-0 gap-1.5", isDragging && "z-20 opacity-70")}
    >
      <div
        {...attributes}
        {...listeners}
        className={cn(
          "relative grid aspect-square cursor-grab place-items-center overflow-hidden rounded-md border bg-panel-inset text-muted-foreground",
          isCover ? "border-primary" : "border-border",
        )}
        aria-label={`${reference.asset_name} · ${roleLabel}`}
      >
        {image ? (
          <img src={assetThumbnailUrl(reference.asset_id)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <Film size={24} strokeWidth={1.4} />
        )}
        <span className="absolute left-1.5 top-1.5 rounded-sm bg-[rgba(10,12,15,0.72)] px-1.5 py-px text-ui-2xs font-medium text-[#e8eaed]" data-reference-role={reference.role}>
          {roleLabel}
        </span>
        {isCover && (
          <span className="absolute bottom-1.5 left-1.5 inline-flex items-center gap-1 rounded-sm bg-primary px-1.5 py-px text-ui-2xs font-medium text-primary-foreground">
            <Star size={10} />
            {t("entityCoverBadge")}
          </span>
        )}
      </div>
      <figcaption className="flex min-w-0 items-center gap-1">
        <OptionPicker
          value={reference.role}
          onChange={onRole}
          options={roles}
          ariaLabel={`${t("entityRole")}: ${reference.asset_name}`}
          size="sm"
          className="min-w-0 flex-1 text-ui-xs"
        />
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`${t("studioActions")}: ${reference.asset_name}`}>
              <MoreHorizontal />
            </Button>
          </PopoverTrigger>
          <PopoverContent className={cn(ACTION_MENU, "w-44")} align="end">
            {image && !isCover && (
              <PopoverClose asChild>
                <Button variant="ghost" className="justify-start" onClick={onCover}>
                  <Star />
                  {t("entitySetCover")}
                </Button>
              </PopoverClose>
            )}
            {!first && (
              <PopoverClose asChild>
                <Button variant="ghost" className="justify-start" onClick={() => onMove(-1)}>
                  <ArrowLeft />
                  {t("entityMoveEarlier")}
                </Button>
              </PopoverClose>
            )}
            {!last && (
              <PopoverClose asChild>
                <Button variant="ghost" className="justify-start" onClick={() => onMove(1)}>
                  <ArrowRight />
                  {t("entityMoveLater")}
                </Button>
              </PopoverClose>
            )}
            <PopoverClose asChild>
              <Button variant="ghost" className="justify-start text-destructive" onClick={onRemove}>
                <Trash2 />
                {t("entityRemoveReference")}
              </Button>
            </PopoverClose>
          </PopoverContent>
        </Popover>
      </figcaption>
    </figure>
  );
}

/** 右边那一栏素材库:图片和视频,能搜;点「+」挂上,或者拖到墙上。已经挂上的标出来。 */
function LibraryPanel({
  workspaceId,
  attached,
  pending,
  onAdd,
}: {
  workspaceId: string;
  attached: Set<string>;
  pending: boolean;
  onAdd: (assetId: string) => void;
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");
  const assets = useQuery({ queryKey: assetKeys.list(workspaceId), queryFn: () => listAssets(workspaceId) });
  const needle = keyword.trim().toLowerCase();
  const items = (assets.data ?? []).filter(
    (asset) => (asset.kind === "image" || asset.kind === "video") && (!needle || asset.name.toLowerCase().includes(needle)),
  );
  return (
    <aside className="grid min-w-0 content-start gap-2 rounded-lg border border-border p-3" aria-label={t("entityLibraryTitle")} data-entity-library="">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
        <Input
          size="sm"
          className="pl-8"
          aria-label={t("entityLibrarySearch")}
          placeholder={t("entityLibrarySearch")}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      {items.length === 0 ? (
        <p className="m-0 py-4 text-center text-ui-xs text-muted-foreground">
          {assets.isPending ? t("pageLoading") : t("entityLibraryEmpty")}
        </p>
      ) : (
        //: 列数跟着宽度走,不写死 3 列:窄窗口里这一栏掉到参考图墙下面、铺满整行,写死 3 列时一张缩略图有半屏大。
        //: **滚动和排格子分两层。** 限高又自带滚动的那一层要是 grid,格子(aspect-square + overflow-hidden,
        //: 自动最小高度是 0)的行会被压扁去凑那个高度 —— 缩略图挤成一条条细缝。外层只管限高滚动,里层按内容排。
        <div className="max-h-[480px] min-w-0 overflow-y-auto overscroll-contain" data-entity-library-scroll="">
          <div className="grid auto-rows-max grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
            {items.map((asset) => (
              <LibraryItem key={asset.id} asset={asset} attached={attached.has(asset.id)} pending={pending} onAdd={() => onAdd(asset.id)} />
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}

function LibraryItem({ asset, attached, pending, onAdd }: { asset: Asset; attached: boolean; pending: boolean; onAdd: () => void }) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `${LIBRARY_PREFIX}${asset.id}`,
    disabled: attached,
  });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform) }}
      className={cn("relative aspect-square overflow-hidden rounded-md border border-border bg-panel-inset", isDragging && "z-30 opacity-80", attached && "opacity-50")}
      title={asset.name}
    >
      <div {...attributes} {...listeners} className="absolute inset-0 cursor-grab">
        {asset.kind === "image" ? (
          <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <span className="grid h-full place-items-center text-muted-foreground">
            <Film size={18} />
          </span>
        )}
      </div>
      {!attached && (
        <Button
          variant="secondary"
          size="icon-xs"
          className="absolute bottom-1 right-1"
          aria-label={t("entityAddReference").replace("{name}", asset.name)}
          disabled={pending}
          onClick={onAdd}
        >
          <Plus />
        </Button>
      )}
    </div>
  );
}
