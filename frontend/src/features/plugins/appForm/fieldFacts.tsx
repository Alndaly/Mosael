import {
  AudioLines,
  Box,
  Brush,
  Dices,
  Film,
  Hash,
  Image as ImageIcon,
  ListFilter,
  MessageSquareText,
  Repeat,
  Scaling,
  ToggleLeft,
  Type,
  type LucideIcon,
} from "lucide-react";

import type { WorkflowFillable } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

type Translate = ReturnType<typeof useI18n>;

/**
 * 应用表单编辑器里一项「长什么样」:种类图标、种类叫什么、现在的值的一句预览、排错用的技术名。编辑器的三块(工作流里能填的、
 * 表单、失效的项)都用这一份,同一种项在哪儿都是同一个图标、同一个说法。
 */

/** 一项在表单上是哪一种控件:文字、提示词框(主提示词)、上传的素材(图 / 视频 / 音频 / 蒙版)、模型、数字、选项、开关、
 *  种子、尺寸、张数。 */
export type FieldVisual =
  | "text" | "prompt" | "image" | "video" | "audio" | "mask" | "model" | "number" | "choice" | "toggle" | "seed" | "size" | "runs";

export function visualOf(item: WorkflowFillable | undefined, main = false): FieldVisual {
  if (!item) return "text";
  if (item.kind === "text") return main ? "prompt" : "text";
  if (item.kind === "media") {
    if (item.media === "video" || item.media === "audio" || item.media === "mask") return item.media;
    return "image";
  }
  return item.kind;
}

const ICONS: Record<FieldVisual, LucideIcon> = {
  text: Type,
  prompt: MessageSquareText,
  image: ImageIcon,
  video: Film,
  audio: AudioLines,
  mask: Brush,
  model: Box,
  number: Hash,
  choice: ListFilter,
  toggle: ToggleLeft,
  seed: Dices,
  size: Scaling,
  runs: Repeat,
};

/** 种类图标:一块小方底,读屏念种类名(「数字」「图片」)。 */
export function KindIcon({ visual, className }: { visual: FieldVisual; className?: string }) {
  const t = useI18n();
  const Icon = ICONS[visual];
  return (
    <span
      role="img"
      aria-label={t(`workflowAppKind_${visual}`)}
      data-field-kind={visual}
      className={cn(
        "grid size-7 shrink-0 place-items-center rounded-md bg-secondary text-muted-foreground [&_svg]:size-3.5",
        visual === "prompt" && "bg-accent text-accent-foreground",
        className,
      )}
    >
      <Icon aria-hidden />
    </span>
  );
}

/** 文件路径只看最后一段(`SDXL/aMix.safetensors` → `aMix.safetensors`)。 */
const basename = (value: string) => value.split(/[\\/]/).pop() || value;

/** 一项现在是什么值的一句话:工作流里存的那个值(长文字只取开头),素材是「用的人上传」,种子「每次随机」。 */
export function valueText(item: WorkflowFillable, t: Translate): string {
  const spec = (item.spec ?? {}) as { default?: unknown };
  const value = spec.default;
  switch (item.kind) {
    case "media":
      return t("workflowAppValueUpload");
    case "seed":
      return t("workflowAppValueRandom");
    case "runs":
      return t("workflowAppValueRuns").replace("{n}", String(typeof value === "number" ? value : 1));
    case "toggle":
      return t(value === true ? "workflowAppValueOn" : "workflowAppValueOff");
    case "model":
      return typeof value === "string" && value ? basename(value) : t("workflowAppValueEmpty");
    default:
      if (value === undefined || value === null || value === "") return t("workflowAppValueEmpty");
      return String(value).replace(/\s+/g, " ").trim().slice(0, 120);
  }
}

/** 排错用的技术名:「节点 #13 · LoraLoader|pysssss · strength_model」。图级的项没有节点,回空串。 */
export function techText(item: WorkflowFillable | undefined, t: Translate): string {
  if (!item?.node) return "";
  return t("workflowAppTech").replace("{node}", item.node).replace("{class}", item.class_type || "?").replace("{input}", item.input);
}
