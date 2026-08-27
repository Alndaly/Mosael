import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Upload, X } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EMPTY_SLOT, ROLE_COPY, isEmptySlot, withSlot, type FrameSlot, type SourceRole } from "@/features/ai-studio/sourceFrames";

/**
 * 一个「带角色的输入素材」槽位:上传/选一张图,或者粘一条外链。
 *
 * 首帧、尾帧、参考图长得一模一样,差的只是称呼 —— 此前它们在生成面板里各占一套(三个配置
 * 字段、一个 ref、一条上传变更、一个清除函数、六十行 JSX)。加尾帧就是把这一整套再抄一遍。
 *
 * 素材和外链**互斥**:填了一个就清掉另一个。两个同时留着的话,后端按素材走,而界面上那条
 * url 还明晃晃写着,用户会以为它生效了。
 *
 * ## 一个角色可以挂多份
 *
 * 参考图能给九张、参考视频三段(上限由描述符的 source_limits 给)。所以这里收的是**一串**
 * 槽位:`limit === 1` 时长得和以前一模一样,没有计数也没有加号;大于 1 时每一份自己一行,
 * 底下一个「再加一份」,加到上限就消失 —— 上限是接口的硬约束,让用户挂到第十张再被拒,
 * 拒的话还是一句说着数组下标的英文。
 */
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
  /** 这个角色最多挂几份。来自描述符的 source_limits,不是我们定的。 */
  limit?: number;
  onChange: (next: FrameSlot[]) => void;
  workspaceId: string;
  /** 这个角色要额外说的一句话(比如首尾帧一起给是什么意思)。 */
  hint?: string;
  /** 另一组正在用 —— 灰掉,并说清楚为什么。 */
  disabled?: boolean;
  disabledReason?: string;
}) {
  const t = useI18n();
  const copy = ROLE_COPY[role];
  const filled = slots.filter((slot) => !isEmptySlot(slot)).length;
  const canAdd = !disabled && slots.length < limit;

  return (
    <div
      className={`grid gap-1.5 text-ui-xs font-semibold text-muted-foreground ${disabled ? "opacity-45" : ""}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span>{t(copy.label)}</span>
        {limit > 1 && (
          <span className="font-normal tabular-nums text-muted-foreground/70">
            {filled}/{limit}
          </span>
        )}
      </div>
      {hint && <span className="font-normal leading-[1.5] text-muted-foreground/80">{hint}</span>}
      {disabled && disabledReason && (
        <span className="font-normal leading-[1.5] text-muted-foreground/80">{disabledReason}</span>
      )}
      {slots.map((slot, index) => (
        <OneSlot
          key={index}
          role={role}
          slot={slot}
          disabled={disabled}
          workspaceId={workspaceId}
          onChange={(next) => onChange(withSlot(slots, index, next))}
        />
      ))}
      {canAdd && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full justify-center"
          onClick={() => onChange([...slots, { ...EMPTY_SLOT }])}
        >
          <Plus size={13} />
          {t("genReferenceAdd")}
        </Button>
      )}
    </div>
  );
}

/** 一份素材。上传/选一张,或者粘一条外链。 */
function OneSlot({
  role,
  slot,
  onChange,
  workspaceId,
  disabled,
}: {
  role: SourceRole;
  slot: FrameSlot;
  onChange: (next: FrameSlot) => void;
  workspaceId: string;
  disabled: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { openImagePreview } = useImagePreview();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const copy = ROLE_COPY[role];

  const upload = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId, file, name: file.name }),
    onSuccess: (asset: Asset) => {
      onChange({ url: "", assetId: asset.id, assetName: asset.name });
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });

  return (
    <div className="grid gap-1.5">
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept={copy.accept}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) upload.mutate(file);
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full justify-center"
        onClick={() => inputRef.current?.click()}
        loading={upload.isPending}
        disabled={disabled}
      >
        <Upload size={13} />
        {upload.isPending ? t(copy.uploading) : t(copy.upload)}
      </Button>
      {slot.assetId && (
        <div className="grid min-h-11 grid-cols-[44px_minmax(0,1fr)_28px] items-center gap-2 rounded-lg border border-border bg-[color-mix(in_srgb,var(--panel)_88%,var(--muted)_12%)] p-[5px]">
          <button
            type="button"
            className="block size-auto h-[34px] w-11 cursor-zoom-in overflow-hidden rounded-lg border border-border bg-muted p-0"
            onClick={() => openImagePreview({ src: assetFileUrl(slot.assetId), title: slot.assetName || t(copy.label) })}
          >
            <img className="block h-full w-full object-cover" src={assetThumbnailUrl(slot.assetId)} alt="" />
          </button>
          <span className="truncate text-xs font-semibold text-foreground" title={slot.assetName}>
            {slot.assetName}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onChange({ ...EMPTY_SLOT })}
            aria-label={t("delete")}
          >
            <X size={13} />
          </Button>
        </div>
      )}
      <label className="grid gap-1.5">
        <span>{t(copy.urlLabel)}</span>
        <Input
          className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-ui-sm font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
          placeholder="https://..."
          disabled={disabled}
          value={slot.url}
          onChange={(event) =>
            // 填了外链就清掉选中的素材 —— 两个都留着的话,后端按素材走,而界面上那条 url
            // 还写着,用户会以为它生效了。
            onChange(event.target.value.trim() ? { url: event.target.value, assetId: "", assetName: "" } : { ...EMPTY_SLOT })
          }
        />
      </label>
    </div>
  );
}
