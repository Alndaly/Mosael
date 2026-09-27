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

import { assetKeys } from "@/api/queryKeys";
import {
  addEntityReference,
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
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ACTION_MENU } from "@/components/ui/floating";
import { useFileDrop } from "@/lib/useFileDrop";
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
export function ReferenceWall({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [order, setOrder] = React.useState<string[]>(() => entity.references.map((one) => one.asset_id));
  React.useEffect(() => setOrder(entity.references.map((one) => one.asset_id)), [entity.references]);
  const byId = new Map(entity.references.map((one) => [one.asset_id, one]));
  const refs = order.map((id) => byId.get(id)).filter((one): one is EntityReference => Boolean(one));

  const settle = (next: Entity) => {
    qc.setQueryData(entityKeys.detail(workspaceId, entity.id), next);
    void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
  };
  const fail = (error: unknown) => toast.error(errorText(error));

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
            {labels.priority.length > 0 && (
              <p className="m-0 text-ui-xs text-muted-foreground" data-attach-order="">
                {t("entityAttachOrder").replace("{order}", labels.priority.join(" > "))}
              </p>
            )}
          </div>
          <span className="flex flex-wrap gap-2">
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
