import React from "react";
import {
  Boxes,
  Eye,
  EyeOff,
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

import { modelPreviewUrl, modelThumbnailUrl, type ModelFile, type ModelNsfw, type ModelNsfwReason } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { previewPick, useModelPreviewSettings, type PreviewTreatment } from "@/components/generation/modelPreviewSettings";
import { Hint } from "@/components/ui/tooltip";
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
 * 模糊的两档(见 modelPreviewSettings)。悬停或键盘聚焦到**外面那一层**(带 `group/thumb` 的卡片、列表行、详情里的
 * 预览框)时看清。只认键盘聚焦(`:focus-visible`):右键菜单关上会把焦点还给卡片,刚标成 NSFW 的那张不该因此露着。
 * 放大一点再模糊:模糊会把边缘晕成半透明,放大后由外层的 `overflow-hidden` 裁掉。
 */
const REVEAL =
  "transition-[filter,transform,opacity] duration-150 motion-reduce:transition-none " +
  "group-hover/thumb:scale-100 group-hover/thumb:blur-none " +
  "group-focus-visible/thumb:scale-100 group-focus-visible/thumb:blur-none " +
  "group-has-[:focus-visible]/thumb:scale-100 group-has-[:focus-visible]/thumb:blur-none";
const BLUR_CLASS: Partial<Record<PreviewTreatment, string>> = {
  light: `scale-105 blur-sm ${REVEAL}`,
  heavy: `scale-110 blur-xl ${REVEAL}`,
};

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
  treatment = "clear",
  play = false,
  onFailed,
}: {
  instanceId: string;
  model: Pick<ModelFile, "folder" | "name" | "has_preview"> & Partial<Pick<ModelFile, "preview_kind">>;
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
  /**
   * 怎么画(见 modelPreviewSettings.previewTreatment):清晰;轻度 / 重度模糊,悬停 / 聚焦到外层 `group/thumb` 时看清;
   * 不显示 —— 不去取图,画按目录分的图标再带一枚「已隐藏」的眼睛。占位图标不模糊(那不是预览图)。
   */
  treatment?: PreviewTreatment;
  /**
   * 预览是一段视频时(`preview_kind: "video"`)播它:静音、循环。卡片悬停、聚焦时给;只在清晰时播 —— 模糊着自己动起来,
   * 等于没糊。平时显示的是它的第一帧(宿主缩好的缩略图)。
   */
  play?: boolean;
  /** 说有预览图、这张却没取到(服务器上那张没了、取的时候连接断了)。占位照样换上;要自己摆占位的调用处听这个。 */
  onFailed?: () => void;
}) {
  const t = useI18n();
  //: 那台服务器上没有、用别处的示例图时挑哪一张跟着 NSFW 那组设置走(见 previewPick)
  const [settings] = useModelPreviewSettings();
  const pick = previewPick(settings);
  const video = model.preview_kind === "video";
  //: 视频的「原图」是那段视频本身,<img> 放不了它:图那一层一律用第一帧(缩略图)
  const src = (full && !video ? modelPreviewUrl : modelThumbnailUrl)(instanceId, model.folder, model.name, pick);
  //: 记的是哪一个地址载好了 / 没取到:同一枚(下拉的触发器)换了文件,上一个文件的结果不带过去。
  const [loaded, setLoaded] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState<string | null>(null);
  const Icon = folderIcon(model.folder);
  const hidden = treatment === "hidden" && model.has_preview;
  if (!model.has_preview || failed === src || hidden) {
    return (
      <span
        aria-hidden
        data-placeholder={model.folder}
        data-hidden-preview={hidden ? "" : undefined}
        className={cn(
          "relative grid place-items-center content-center gap-1.5 bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] text-primary",
          className,
        )}
      >
        <Icon className={compact ? "size-4 opacity-70" : "size-8 opacity-70"} />
        {!compact && <span className="text-ui-2xs font-medium text-muted-foreground">{hidden ? t("modelPreviewHidden") : model.folder}</span>}
        {hidden && compact && <EyeOff aria-hidden className="absolute bottom-0.5 right-0.5 size-2.5 text-muted-foreground" />}
      </span>
    );
  }
  //: 载好之前一直是透明的(框照样占着位置,不跳),载好了再淡入。取不到时浏览器会先画一帧「碎图」(图标加替代文字),
  //: 等换成占位已经晚了 —— 透明着的那张碎图谁也看不见,下一帧就是占位。
  const poster = (
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
      data-treatment={treatment}
      className={cn(
        "bg-secondary object-cover opacity-0 transition-opacity duration-150 motion-reduce:transition-none data-[loaded]:opacity-100",
        BLUR_CLASS[treatment],
        className,
      )}
    />
  );
  if (!video || !play || treatment !== "clear") return poster;
  return (
    <>
      {poster}
      {/* 叠在第一帧上播:同一个框、同样的裁切;播不了就还是第一帧 */}
      <video
        data-preview-video=""
        src={modelPreviewUrl(instanceId, model.folder, model.name, pick)}
        muted
        loop
        autoPlay
        playsInline
        aria-hidden
        className={cn("pointer-events-none absolute inset-0 size-full object-cover", className)}
      />
    </>
  );
}

/** 预览图不是那台服务器上的(那边没有,Mosael 用了别处的示例图)时,卡片角上那一枚:「Civitai」。悬停说清只在 Mosael 里显示。 */
export function PreviewOriginMark({ origin, className }: { origin: string | undefined; className?: string }) {
  const t = useI18n();
  if (!origin || origin === "server") return null;
  const site = SITE_NAMES[origin] ?? origin;
  return (
    <Hint label={t("modelPreviewFromSite").replace("{site}", site)} hint={t("modelPreviewFromSiteHint")}>
      <span
        data-preview-origin={origin}
        tabIndex={0}
        aria-label={t("modelPreviewFromSite").replace("{site}", site)}
        className={cn(
          "relative z-10 inline-flex h-5 items-center rounded-full bg-[color-mix(in_srgb,var(--panel)_88%,transparent)] px-1.5 text-ui-2xs font-semibold leading-none text-foreground shadow-[var(--shadow-floating)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        {site}
      </span>
    </Hint>
  );
}

/** 别处的站叫什么(插件报的 `site`)。 */
const SITE_NAMES: Record<string, string> = { civitai: "Civitai", huggingface: "HuggingFace", modelscope: "ModelScope" };

/** 一条 NSFW 依据说成人话(悬停时列出来)。 */
export function nsfwReasonText(reason: ModelNsfwReason, t: ReturnType<typeof useI18n>): string {
  if (reason.source === "civitai") {
    if (reason.level != null) {
      return t("modelNsfwCivitaiImage").replace("{level}", CIVITAI_LEVELS[reason.level] ?? String(reason.level));
    }
    return t(reason.nsfw ? "modelNsfwCivitaiModel" : "modelNsfwCivitaiModelSafe");
  }
  if (reason.source === "local") {
    const percent = Math.round((reason.score ?? 0) * 100);
    return t("modelNsfwLocal").replace("{percent}", String(percent));
  }
  const parts = [
    reason.tags?.length ? t("modelNsfwTags").replace("{tags}", reason.tags.join(", ")) : "",
    reason.words?.length ? t("modelNsfwWords").replace("{words}", reason.words.join(", ")) : "",
  ].filter(Boolean);
  return parts.join(";");
}

/** Civitai 的分级(nsfwLevel)→ 它网站上的叫法。 */
const CIVITAI_LEVELS: Record<number, string> = { 1: "PG", 2: "PG-13", 4: "R", 8: "X", 16: "XXX" };

/** 合成的判断说成人话:第一行结论(手动标的说手动标的),下面每条依据一句。 */
export function nsfwSummary(nsfw: ModelNsfw, t: ReturnType<typeof useI18n>): { label: string; reasons: string[] } {
  const label =
    nsfw.manual === true ? t("modelNsfwManualYes")
    : nsfw.manual === false ? t("modelNsfwManualNo")
    : nsfw.flagged ? t("modelNsfwAuto")
    : t("modelNsfwNone");
  return { label, reasons: (nsfw.reasons ?? []).map((reason) => nsfwReasonText(reason, t)).filter(Boolean) };
}

/**
 * 判成 NSFW 的那一枚角标:卡片、列表行、下拉的缩略图上。悬停说凭什么(手动标的、Civitai 的分级、本机识别、
 * 训练标签和名字里的词)。没判成 NSFW 的不画 —— 那不是「安全」的担保,只是没有依据。
 */
export function NsfwMark({ nsfw, className }: { nsfw: ModelNsfw | undefined; className?: string }) {
  const t = useI18n();
  if (!nsfw?.flagged) return null;
  const summary = nsfwSummary(nsfw, t);
  return (
    <Hint label={summary.label} hint={summary.reasons.join(" · ") || undefined}>
      <span
        data-nsfw-mark=""
        tabIndex={0}
        aria-label={[summary.label, ...summary.reasons].join(";")}
        className={cn(
          "relative z-10 inline-flex h-5 items-center rounded-full bg-[color-mix(in_srgb,var(--destructive)_88%,transparent)] px-1.5 text-ui-2xs font-semibold leading-none text-white",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        {t("modelNsfwBadge")}
      </span>
    </Hint>
  );
}
