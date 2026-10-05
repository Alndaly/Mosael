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

import { modelPreviewUrl, modelThumbnailUrl, type ModelFile } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/**
 * 模型文件的缩略图(ADR 0034):模型库的卡片和生成表单里选大模型 / LoRA 的下拉共用这一个。
 *
 * 有预览图用宿主的地址(宿主按插件给的地址取回、缓存;默认要缩略图,详情页的大图要原图);没有、或者取不到,就是
 * **按目录分的占位** —— 大模型、LoRA、VAE、放大……各一个图标,不留白、不放一张碎图(没载好的图是透明的)。
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

/**
 * 预览图先模糊(模型库的「模糊预览图」开关)。悬停或键盘聚焦到**外面那一层**(带 `group/thumb` 的卡片、列表行、
 * 详情里的预览框)时看清。放大一点再模糊:模糊会把边缘晕成半透明,放大后由外层的 `overflow-hidden` 裁掉。
 */
const BLURRED =
  "scale-110 blur-xl transition-[filter,transform,opacity] duration-150 motion-reduce:transition-none " +
  "group-hover/thumb:scale-100 group-hover/thumb:blur-none group-focus-within/thumb:scale-100 group-focus-within/thumb:blur-none";

/**
 * 图还没载完就被拿下来(滚出了按需画的那几行、换了目录、关了弹窗):把请求掐掉。浏览器不会因为 `<img>` 离开了页面就
 * 不取了 —— 一路滚过去的几百张会一直占着到宿主的那几条连接,宿主还要挨个去那台服务器取原图,眼前这几张排在它们后面
 * 干等。去掉 src(不是设成空串):请求掐掉,不发 error 事件。
 */
function abortUnfinished(img: HTMLImageElement | null) {
  if (!img) return;
  return () => {
    if (!img.complete) img.removeAttribute("src");
  };
}

export function ModelThumb({
  instanceId,
  model,
  className,
  compact = false,
  full = false,
  blurred = false,
  onFailed,
}: {
  instanceId: string;
  model: Pick<ModelFile, "folder" | "name" | "has_preview">;
  /**
   * 图片和占位**共用**。占位没有固有尺寸,所以这里要给出一个框(`aspect-*`、`size-*`,或外层用 `[&>*]:size-full`
   * 撑满);只给 `max-h` + `w-full`、靠图片自己的宽高撑开的(详情页的预览框),占位就只剩一条图标那么高 ——
   * 那种调用处用 `onFailed` 换成自己的框。
   */
  className?: string;
  /** 小图(下拉里那一格、触发器里那一枚):占位只画图标,不写目录名。 */
  compact?: boolean;
  /**
   * 用原图(详情页的大图)。默认是宿主缩好的缩略图(长边 512):卡片、列表行、下拉一屏几十张,每张都解一张
   * 一两千像素的原图,滚动和悬停都卡。
   */
  full?: boolean;
  /** 先模糊,悬停 / 聚焦到外层 `group/thumb` 时看清。占位图标不模糊(那不是预览图)。 */
  blurred?: boolean;
  /** 说有预览图、这张却没取到(服务器上那张没了、取的时候连接断了)。占位照样换上;要自己摆占位的调用处听这个。 */
  onFailed?: () => void;
}) {
  const t = useI18n();
  const src = (full ? modelPreviewUrl : modelThumbnailUrl)(instanceId, model.folder, model.name);
  //: 记的是哪一个地址载好了 / 没取到:同一枚(下拉的触发器)换了文件,上一个文件的结果不带过去。
  const [loaded, setLoaded] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState<string | null>(null);
  const Icon = folderIcon(model.folder);
  if (!model.has_preview || failed === src) {
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
  //: 载好之前一直是透明的(框照样占着位置,不跳),载好了再淡入。取不到时浏览器会先画一帧「碎图」(图标加替代文字),
  //: 等换成占位已经晚了 —— 透明着的那张碎图谁也看不见,下一帧就是占位。
  return (
    <img
      ref={abortUnfinished}
      src={src}
      alt={compact ? "" : t("modelPreviewAlt").replace("{name}", modelBaseName(model.name))}
      loading="lazy"
      decoding="async"
      onLoad={() => setLoaded(src)}
      onError={() => {
        setFailed(src);
        onFailed?.();
      }}
      data-loaded={loaded === src ? "" : undefined}
      data-blurred={blurred ? "" : undefined}
      className={cn(
        "bg-secondary object-cover opacity-0 transition-opacity duration-150 motion-reduce:transition-none data-[loaded]:opacity-100",
        blurred && BLURRED,
        className,
      )}
    />
  );
}
