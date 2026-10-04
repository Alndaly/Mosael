import React from "react";
import {
  Boxes,
  Eye,
  FileBox,
  ImagePlus,
  Layers,
  Maximize2,
  Palette,
  ScanFace,
  Sparkles,
  Spline,
  Tag,
  Type,
  type LucideIcon,
} from "lucide-react";

import { modelPreviewUrl, type ModelFile } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/**
 * 模型文件的缩略图(ADR 0034):模型库的卡片和生成表单里选大模型 / LoRA 的下拉共用这一个。
 *
 * 有预览图用宿主的预览地址(宿主按插件给的地址取回、缓存);没有、或者取不到,就是**按目录分的占位** ——
 * 大模型、LoRA、VAE、放大……各一个图标,不留白、不放一张碎图。
 */

/** 目录 → 没有预览图时占位用的图标。认不出的目录用通用的文件图标。 */
const FOLDER_ICONS: Record<string, LucideIcon> = {
  checkpoints: Boxes,
  loras: Layers,
  lycoris: Layers,
  vae: Palette,
  vae_approx: Palette,
  text_encoders: Type,
  clip: Type,
  clip_gguf: Type,
  diffusion_models: Sparkles,
  unet: Sparkles,
  unet_gguf: Sparkles,
  controlnet: Spline,
  upscale_models: Maximize2,
  embeddings: Tag,
  clip_vision: Eye,
  ipadapter: ImagePlus,
  ultralytics: ScanFace,
  ultralytics_bbox: ScanFace,
  ultralytics_segm: ScanFace,
};

export function folderIcon(folder: string): LucideIcon {
  return FOLDER_ICONS[folder] ?? FileBox;
}

/** ComfyUI 在 Windows 上报的相对路径用反斜杠,工作流里存的有时是正斜杠:比较前统一。 */
export const normModelName = (name: string) => name.replace(/\\/g, "/").trim();
export const modelBaseName = (name: string) => normModelName(name).split("/").pop() || name;
export const modelSubFolder = (name: string) => normModelName(name).split("/").slice(0, -1).join("/");

export function ModelThumb({
  instanceId,
  model,
  className,
  compact = false,
}: {
  instanceId: string;
  model: Pick<ModelFile, "folder" | "name" | "has_preview">;
  className?: string;
  /** 小图(下拉里那一格、触发器里那一枚):占位只画图标,不写目录名。 */
  compact?: boolean;
}) {
  const t = useI18n();
  const [failed, setFailed] = React.useState(false);
  const Icon = folderIcon(model.folder);
  if (!model.has_preview || failed) {
    return (
      <span
        aria-hidden
        data-placeholder={model.folder}
        className={cn(
          "grid place-items-center content-center gap-1.5 bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] text-primary",
          className,
        )}
      >
        <Icon className={compact ? "size-4 opacity-70" : "size-8 opacity-70"} />
        {!compact && <span className="text-ui-2xs font-medium text-muted-foreground">{model.folder}</span>}
      </span>
    );
  }
  return (
    <img
      src={modelPreviewUrl(instanceId, model.folder, model.name)}
      alt={compact ? "" : t("modelPreviewAlt").replace("{name}", modelBaseName(model.name))}
      loading="lazy"
      onError={() => setFailed(true)}
      className={cn("bg-secondary object-cover", className)}
    />
  );
}
