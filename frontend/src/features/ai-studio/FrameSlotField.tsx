import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Music, Plus, X } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { Button } from "@/components/ui/button";
import { EMPTY_SLOT, ROLE_COPY, isEmptySlot, type FrameSlot, type SourceRole } from "@/features/ai-studio/sourceFrames";

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

/** 一格素材的尺寸:够看清是什么,又不至于把面板撑开。 */
const TILE = "grid aspect-video w-full place-items-center overflow-hidden rounded-lg border border-border bg-muted/40";

function useUpload(workspaceId: string, onDone: (assets: Asset[]) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) =>
      Promise.all(files.map((file) => importAsset({ workspaceId, file, name: file.name }))),
    onSuccess: (assets: Asset[]) => {
      onDone(assets);
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
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
}: {
  slot: FrameSlot | null;
  role: SourceRole;
  disabled: boolean;
  onPick: (files: File[]) => void;
  onClear?: () => void;
  multiple: boolean;
  label?: string;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const copy = ROLE_COPY[role];
  const isAudio = copy.accept.startsWith("audio");

  if (slot && !isEmptySlot(slot)) {
    return (
      <div className="relative">
        <button
          type="button"
          className={`${TILE} cursor-zoom-in p-0`}
          onClick={() =>
            isAudio
              ? undefined
              : openImagePreview({ src: assetFileUrl(slot.assetId), title: slot.assetName || t(copy.label) })
          }
        >
          {isAudio ? (
            <span className="flex items-center gap-1.5 px-2 text-ui-xs font-semibold text-muted-foreground">
              <Music size={13} />
              <span className="truncate">{slot.assetName}</span>
            </span>
          ) : (
            <img className="block h-full w-full object-cover" src={assetThumbnailUrl(slot.assetId)} alt="" />
          )}
        </button>
        {onClear && !disabled && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1 h-5 w-5 rounded-full bg-background/85 hover:bg-background"
            onClick={onClear}
            aria-label={t("delete")}
          >
            <X size={11} />
          </Button>
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
      <button
        type="button"
        disabled={disabled}
        className={`${TILE} cursor-pointer gap-1 border-dashed text-ui-xs font-semibold text-muted-foreground hover:border-primary/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60`}
        onClick={() => inputRef.current?.click()}
      >
        <Plus size={14} />
        {label && <span className="px-1 text-center leading-tight">{label}</span>}
      </button>
    </>
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
}: {
  role: SourceRole;
  slots: FrameSlot[];
  limit?: number;
  onChange: (next: FrameSlot[]) => void;
  workspaceId: string;
  hint?: string;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const t = useI18n();
  const copy = ROLE_COPY[role];
  const filled = slots.filter((one) => !isEmptySlot(one));
  // 选多了就按剩余名额截断 —— 用户的意图很清楚(这些都要),为超出的那两张弹个错没有意义。
  const upload = useUpload(workspaceId, (assets) =>
    onChange([...filled, ...assets.map(slotOf)].slice(0, limit)),
  );
  const canAdd = !disabled && filled.length < limit;

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
      <div className="grid grid-cols-3 gap-1.5">
        {filled.map((slot, index) => (
          <Tile
            key={slot.assetId || index}
            slot={slot}
            role={role}
            disabled={disabled}
            multiple={limit > 1}
            onPick={() => undefined}
            onClear={() => onChange(filled.filter((_, i) => i !== index))}
          />
        ))}
        {canAdd && (
          <Tile
            slot={null}
            role={role}
            disabled={upload.isPending}
            multiple={limit > 1}
            onPick={(files) => upload.mutate(files)}
            label={upload.isPending ? t(copy.uploading) : undefined}
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
            label={t("genFirstFrame")}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="mx-auto h-6 w-6"
            disabled={!canSwap}
            onClick={() => onChange({ first: last, last: first })}
            aria-label={t("genSwapKeyframes")}
            title={t("genSwapKeyframes")}
          >
            <ArrowLeftRight size={13} />
          </Button>
          <Tile
            slot={lastSlot}
            role="last_frame"
            disabled={disabled || uploadLast.isPending}
            multiple={false}
            onPick={(files) => uploadLast.mutate(files.slice(0, 1))}
            onClear={() => onChange({ first, last: [{ ...EMPTY_SLOT }] })}
            label={t("genLastFrame")}
          />
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5">
          <Tile
            slot={firstSlot}
            role="first_frame"
            disabled={disabled || uploadFirst.isPending}
            multiple={false}
            onPick={(files) => uploadFirst.mutate(files.slice(0, 1))}
            onClear={() => onChange({ first: [{ ...EMPTY_SLOT }], last })}
          />
        </div>
      )}
    </div>
  );
}
