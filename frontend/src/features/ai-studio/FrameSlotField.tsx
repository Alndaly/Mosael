import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, X } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EMPTY_SLOT, ROLE_COPY, type FrameSlot, type SourceRole } from "@/features/ai-studio/sourceFrames";

/**
 * 一个「带角色的输入素材」槽位:上传/选一张图,或者粘一条外链。
 *
 * 首帧、尾帧、参考图长得一模一样,差的只是称呼 —— 此前它们在生成面板里各占一套(三个配置
 * 字段、一个 ref、一条上传变更、一个清除函数、六十行 JSX)。加尾帧就是把这一整套再抄一遍。
 *
 * 素材和外链**互斥**:填了一个就清掉另一个。两个同时留着的话,后端按素材走,而界面上那条
 * url 还明晃晃写着,用户会以为它生效了。
 */
export function FrameSlotField({
  role,
  slot,
  onChange,
  workspaceId,
  hint,
}: {
  role: SourceRole;
  slot: FrameSlot;
  onChange: (next: FrameSlot) => void;
  workspaceId: string;
  /** 这个角色要额外说的一句话(比如首尾帧一起给是什么意思)。 */
  hint?: string;
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
    <div className="grid gap-1.5 text-ui-xs font-semibold text-muted-foreground">
      <span>{t(copy.label)}</span>
      {hint && <span className="font-normal leading-[1.5] text-muted-foreground/80">{hint}</span>}
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept="image/*"
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
