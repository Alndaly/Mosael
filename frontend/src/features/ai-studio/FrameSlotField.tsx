import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Music, Pencil, Plus, X } from "lucide-react";

import { assetPreviewUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/utils";
import { Truncate } from "@/components/ui/truncate";
import { EMPTY_SLOT, ROLE_COPY, isEmptySlot, slotColumns, type FrameSlot, type SourceRole } from "@/lib/sourceFrames";

/**
 * 「带角色的输入素材」在面板里的样子:**一格一格的缩略图**,不是一行一行的表单。
 *
 * 此前每个角色占五行(标题、说明、上传按钮、URL 标签、URL 输入框),再加一个「再加一份」。
 * 火山那种支持首帧 + 尾帧 + 参考图 + 参考视频 + 参考音频的模型,光素材区就三十多行 ——
 * 面板滚三屏才到底,而用户真正要看的是"我挂了哪几张图",那恰恰是唯一看不见的东西。
 *
 * 现在一个角色一行缩略图:挂了什么一眼看得见,加号在末尾,加到上限就消失。
 *
 * ## 三处刻意的取舍
 *
 * **一次能选多个文件。** 参考图能挂九张,让用户点九次上传是没有道理的。选多了就按剩余
 * 名额截断,而不是报错 —— 用户的意图很清楚,是"这些都要"。
 *
 * **没有 URL 输入框。** 那一栏几乎没人用(素材本来就在素材库里),却让每个角色多占两行。
 * 外链这条路本身留着(智能体和工作流照样能发 `<role>_url`,见 ai/providers/base),
 * 只是不再占据面板。
 *
 * **首尾帧左右并排,中间一个交换箭头。** 它俩天然是一对(从这一格动到那一格),而竖着排
 * 的时候完全看不出这层关系;拍错顺序也是常事,所以给一个原地对调,而不是让用户删掉重传。
 */

/** 一格素材。
 *
 * **固定高度而不是固定比例。** 用 aspect-video 的话,一行只挂一份时那一格会被拉成整个面板宽
 * (280×157),一个空的加号占掉半屏;而挂满三份时又缩成邮票。固定高度让"一份"和"三份"看起来
 * 是同一种东西,只是宽窄不同。
 */
const TILE = "grid h-[68px] w-full place-items-center overflow-hidden rounded-lg border border-border bg-muted/40";

function useUpload(workspaceId: string, onDone: (assets: Asset[]) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) =>
      Promise.all(files.map((file) => importAsset({ workspaceId, file, name: file.name }))),
    onSuccess: (assets: Asset[]) => {
      onDone(assets);
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
    },
  });
}

function slotOf(asset: Asset): FrameSlot {
  return { url: "", assetId: asset.id, assetName: asset.name };
}

/** 一格:空的是个加号,填了的是缩略图 + 一个移除角标。 */
function Tile({
  slot,
  role,
  disabled,
  onPick,
  onClear,
  multiple,
  label,
  name,
  onDraw,
  onEdit,
}: {
  slot: FrameSlot | null;
  role: SourceRole;
  disabled: boolean;
  onPick: (files: File[]) => void;
  onClear?: () => void;
  multiple: boolean;
  label?: string;
  /** 这一格叫什么(模型给的槽位名字,见 sourceLabels):填了的那一格角上标着它,悬停说明里也有。 */
  name?: string;
  /** 空槽旁边的第二格「画一张」(只有调用方说这一格能画时才有,见 FrameSlotField)。 */
  onDraw?: () => void;
  /** 填了的那一格角上的「编辑」入口。 */
  onEdit?: () => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const copy = ROLE_COPY[role];
  const isAudio = copy.accept.startsWith("audio");

  if (slot && !isEmptySlot(slot)) {
    const named = name ? `${name} · ${slot.assetName || t(copy.label)}` : slot.assetName || t(copy.label);
    return (
      <div className="relative" data-slot-name={name || undefined}>
        {isAudio ? (
          <button type="button" className={`${TILE} cursor-zoom-in p-0`}>
            <span className="flex min-w-0 items-center gap-1.5 px-2 text-ui-xs font-semibold text-muted-foreground">
              <Music size={13} className="shrink-0" />
              <Truncate>{slot.assetName}</Truncate>
            </span>
          </button>
        ) : (
          //: 只有一张缩略图:名字放进悬停说明(也是读屏念的名字)。
          <IconButton
            unstyled
            className={`${TILE} relative cursor-zoom-in p-0`}
            label={named}
            onClick={() => openImagePreview({ src: assetPreviewUrl(slot.assetId), title: named })}
          >
            {/* 绝对定位填满:此前是 h-full —— 而这颗按钮是 grid + place-items-center 的行,
                行高由内容定、内容的 100% 又指着行高,百分比没着落,缩略图按原图比例渲染
                (实测 68px 的格里画了张 149px 的图,只看得见中间一截)。 */}
            <img className="absolute inset-0 block size-full object-cover" src={assetThumbnailUrl(slot.assetId)} alt="" />
          </IconButton>
        )}
        {name && (
          <span className="pointer-events-none absolute bottom-1 left-1 flex max-w-[calc(100%-8px)] rounded bg-background/85 px-1 text-ui-2xs font-semibold text-foreground">
            <Truncate>{name}</Truncate>
          </span>
        )}
        {onEdit && !disabled && (
          //: 蒙版的「编辑」:不占新的格,压在缩略图左上角 —— 右上角是移除,右下角是名字。
          <IconButton
            variant="ghost"
            size="icon-xs"
            shape="round"
            className="absolute left-1 top-1 bg-background/85 hover:bg-background"
            onClick={onEdit}
            label={t("maskEdit")}
            hint={t("maskEditHint")}
          >
            <Pencil size={13} />
          </IconButton>
        )}
        {onClear && !disabled && (
          <IconButton
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1 h-5 w-5 rounded-full bg-background/85 hover:bg-background"
            onClick={onClear}
            label={t("delete")}
          >
            <X size={11} />
          </IconButton>
        )}
      </div>
    );
  }

  return (
    <>
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        multiple={multiple}
        accept={copy.accept}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length) onPick(files);
        }}
      />
      <EmptyTile
        disabled={disabled}
        label={label}
        //: 没有名字的格子(多数角色):只有一个加号,角色名放进悬停说明(也是读屏念的名字)。
        name={t(copy.label)}
        icon={<Plus size={14} />}
        onActivate={() => inputRef.current?.click()}
      />
      {onDraw && (
        //: 「画一张」:和上传那一格并排的第二格。上传还是原来那一格(点它照旧选文件),这里只是多一条路。
        <EmptyTile disabled={disabled} label={t("maskDraw")} icon={<Pencil size={14} />} hint={t("maskDrawHint")} onActivate={onDraw} />
      )}
    </>
  );
}

/** 空槽那一格:一根虚线框 + 图标 + 名字,点一下做一件事(选文件、或者开蒙版编辑器)。
 *
 * 上传那一格和「画一张」那一格长得一样(并排的两格,一大一小才怪),所以只有这一份实现:
 * 有名字就是一颗带字按钮,只有图标就是 IconButton(名字给读屏和悬停说明)。
 */
function EmptyTile({
  label,
  name,
  icon,
  hint,
  disabled,
  onActivate,
}: {
  label?: string;
  name?: string;
  icon: React.ReactNode;
  hint?: string;
  disabled: boolean;
  onActivate: () => void;
}) {
  const className = cn(
    TILE,
    "cursor-pointer border-dashed font-semibold text-muted-foreground hover:border-primary/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60",
  );
  if (!label) {
    return (
      <IconButton unstyled disabled={disabled} label={name ?? ""} hint={hint} className={className} onClick={onActivate}>
        {icon}
      </IconButton>
    );
  }
  return (
    <button type="button" disabled={disabled} className={className} onClick={onActivate}>
      {/* 图标和名字**排一行**。竖着摞的时候,两者之间那道空白比它俩加起来还高。 */}
      <span className="flex min-w-0 items-center gap-1 px-1.5">
        <span className="shrink-0">{icon}</span>
        <Truncate>{label}</Truncate>
      </span>
    </button>
  );
}

/** 一个角色的全部素材:一行缩略图 + 末尾一个加号。 */
export function FrameSlotField({
  role,
  slots,
  limit = 1,
  onChange,
  workspaceId,
  hint,
  disabled = false,
  disabledReason,
  names = [],
  onDrawMask,
  onEditMask,
}: {
  role: SourceRole;
  slots: FrameSlot[];
  limit?: number;
  onChange: (next: FrameSlot[]) => void;
  workspaceId: string;
  hint?: string;
  disabled?: boolean;
  disabledReason?: string;
  /** 槽位按顺序叫什么(描述符的 `source_labels`):第 i 格标第 i 个名字,加号上写下一格的名字。 */
  names?: string[];
  /**
   * **这一格能画** —— 由调用方说(蒙版角色 + 调用方给了这个回调):空槽多一格「画一张」,点它开蒙版编辑器
   * (ADR 0056 第二步)。控件自己不发明这条路:不传就是原来那一个加号格。
   */
  onDrawMask?: () => void;
  /** 已经填了的那一格能改时给这个:缩略图左上角多一个「编辑蒙版」。 */
  onEditMask?: (slot: FrameSlot) => void;
}) {
  const t = useI18n();
  const copy = ROLE_COPY[role];
  const filled = slots.filter((one) => !isEmptySlot(one));
  // 选多了就按剩余名额截断 —— 用户的意图很清楚(这些都要),为超出的那两张弹个错没有意义。
  const upload = useUpload(workspaceId, (assets) =>
    onChange([...filled, ...assets.map(slotOf)].slice(0, limit)),
  );
  const canAdd = !disabled && filled.length < limit;
  //: 画蒙版只对**蒙版**这一格成立:传错了(或者在音频格上顺手传了一个)也不至于在一格音频旁边长出一支笔。
  const maskRole = role === "mask" && !disabled;
  const canDraw = maskRole && canAdd && Boolean(onDrawMask);
  const canEdit = maskRole && Boolean(onEditMask);

  return (
    <div className={`grid gap-1.5 text-ui-xs font-semibold text-muted-foreground ${disabled ? "opacity-45" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <span>{t(copy.label)}</span>
        {limit > 1 && (
          <span className="font-normal tabular-nums text-muted-foreground/70">
            {filled.length}/{limit}
          </span>
        )}
      </div>
      {hint && <span className="font-normal leading-[1.5] text-muted-foreground/80">{hint}</span>}
      {disabled && disabledReason && (
        <span className="font-normal leading-[1.5] text-muted-foreground/80">{disabledReason}</span>
      )}
      <div
        className="grid gap-1.5"
        //: 列数跟着**实际会画出来的格子数**走(上传那一格 + 「画一张」那一格),不写死。
        style={{ gridTemplateColumns: slotColumns(filled.length + (canAdd ? 1 : 0) + (canDraw ? 1 : 0)) }}
      >
        {filled.map((slot, index) => (
          <Tile
            key={slot.assetId || index}
            slot={slot}
            role={role}
            disabled={disabled}
            multiple={limit > 1}
            onPick={() => undefined}
            onClear={() => onChange(filled.filter((_, i) => i !== index))}
            name={names[index] || undefined}
            onEdit={canEdit && onEditMask ? () => onEditMask(slot) : undefined}
          />
        ))}
        {canAdd && (
          <Tile
            slot={null}
            role={role}
            disabled={upload.isPending}
            multiple={limit > 1}
            onPick={(files) => upload.mutate(files)}
            //: 能画的时候,上传那一格也写清楚自己是哪一条路(两格并排,"+"和"画笔"光看图标分不出来)。
            label={upload.isPending ? t(copy.uploading) : names[filled.length] || (canDraw ? t("maskUpload") : undefined)}
            onDraw={canDraw ? onDrawMask : undefined}
          />
        )}
      </div>
    </div>
  );
}

/**
 * 首帧和尾帧并排,中间一个交换箭头。
 *
 * 它俩是一对:成片从左边那一格动到右边那一格。竖着排的时候这层关系完全看不出来,而"拍反了"
 * 又是最常见的手误 —— 所以给一个原地对调,而不是删掉两张重传。
 */
export function KeyframePairField({
  first,
  last,
  onChange,
  workspaceId,
  hint,
  disabled = false,
  disabledReason,
  showLast,
  names = {},
}: {
  first: FrameSlot[];
  last: FrameSlot[];
  onChange: (next: { first: FrameSlot[]; last: FrameSlot[] }) => void;
  workspaceId: string;
  hint?: string;
  disabled?: boolean;
  disabledReason?: string;
  /** 有些模型只认首帧 —— 那就只画左边一格,不画箭头。 */
  showLast: boolean;
  /** 首帧 / 尾帧那一格叫什么(描述符的 `source_labels`);没给就是「首帧」「尾帧」。 */
  names?: { first?: string; last?: string };
}) {
  const t = useI18n();
  const firstSlot = first[0] ?? EMPTY_SLOT;
  const lastSlot = last[0] ?? EMPTY_SLOT;
  const uploadFirst = useUpload(workspaceId, (assets) => onChange({ first: [slotOf(assets[0])], last }));
  const uploadLast = useUpload(workspaceId, (assets) => onChange({ first, last: [slotOf(assets[0])] }));
  const canSwap = !disabled && !isEmptySlot(firstSlot) && !isEmptySlot(lastSlot);

  return (
    <div className={`grid gap-1.5 text-ui-xs font-semibold text-muted-foreground ${disabled ? "opacity-45" : ""}`}>
      <span>{showLast ? t("genKeyframes") : t("genFirstFrame")}</span>
      {hint && <span className="font-normal leading-[1.5] text-muted-foreground/80">{hint}</span>}
      {disabled && disabledReason && (
        <span className="font-normal leading-[1.5] text-muted-foreground/80">{disabledReason}</span>
      )}
      {showLast ? (
        <div className="grid grid-cols-[minmax(0,1fr)_28px_minmax(0,1fr)] items-center gap-1">
          <Tile
            slot={firstSlot}
            role="first_frame"
            disabled={disabled || uploadFirst.isPending}
            multiple={false}
            onPick={(files) => uploadFirst.mutate(files.slice(0, 1))}
            onClear={() => onChange({ first: [{ ...EMPTY_SLOT }], last })}
            label={names.first || t("genFirstFrame")}
            name={names.first}
          />
          <IconButton
            variant="ghost"
            size="icon"
            className="mx-auto h-6 w-6"
            disabled={!canSwap}
            onClick={() => onChange({ first: last, last: first })}
            label={t("genSwapKeyframes")}
            //: 整组被锁住时上面已经写了原因;这里只说「少了一张」这一种。
            disabledReason={!disabled && !canSwap ? t("genSwapKeyframesNeedsBoth") : undefined}
          >
            <ArrowLeftRight size={13} />
          </IconButton>
          <Tile
            slot={lastSlot}
            role="last_frame"
            disabled={disabled || uploadLast.isPending}
            multiple={false}
            onPick={(files) => uploadLast.mutate(files.slice(0, 1))}
            onClear={() => onChange({ first, last: [{ ...EMPTY_SLOT }] })}
            label={names.last || t("genLastFrame")}
            name={names.last}
          />
        </div>
      ) : (
        <div className="grid gap-1.5">
          <Tile
            slot={firstSlot}
            role="first_frame"
            disabled={disabled || uploadFirst.isPending}
            multiple={false}
            onPick={(files) => uploadFirst.mutate(files.slice(0, 1))}
            onClear={() => onChange({ first: [{ ...EMPTY_SLOT }], last })}
            label={names.first}
            name={names.first}
          />
        </div>
      )}
    </div>
  );
}
