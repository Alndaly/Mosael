import { Clapperboard, Film, Languages, Layers, type LucideIcon, Scissors, Shirt, ShoppingBag, Smartphone, Workflow } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 社区卡片左上角那块图标。
 *
 * 插件清单里没有图标,硬塞一个通用拼图块的话,一屏卡片长得一模一样,扫一眼分不出谁是谁。
 * 这里用**名字的第一个字**加一个按 id 固定的色相:同一个插件在列表、详情、推荐位上永远是
 * 同一块颜色,认得出来。官方工作流有明确的用途,用对应的图标(和应用里「工作流社区」同一套);
 * 作者上传了封面图的,用封面。
 */
const HUES = ["--tile-1", "--tile-2", "--tile-3", "--tile-4", "--tile-5", "--tile-6"] as const;

function hueOf(seed: string): string {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return `var(${HUES[hash % HUES.length]})`;
}

const SIZES = {
  sm: "size-10 rounded-lg text-base",
  md: "size-12 rounded-xl text-lg",
  lg: "size-16 rounded-2xl text-2xl",
} as const;

function tileStyle(seed: string) {
  const hue = hueOf(seed);
  return { color: hue, backgroundColor: `color-mix(in oklab, ${hue} 14%, var(--card))` };
}

/** 封面图:作者上传的,尺寸不定,不走 next/image(它只认白名单里的主机)。 */
function Cover({ src, size }: { src: string; size: keyof typeof SIZES }) {
  // oxlint-disable-next-line nextjs/no-img-element
  return <img src={src} alt="" loading="lazy" className={cn("shrink-0 bg-muted object-cover", SIZES[size])} />;
}

export function PluginTile({ seed, name, cover, size = "md" }: { seed: string; name: string; cover?: string | null; size?: keyof typeof SIZES }) {
  if (cover) return <Cover src={cover} size={size} />;
  // 「Amazon S3」取 A,「腾讯云 COS」取 腾 —— 按字形取,不按 UTF-16 码元。
  const initial = Array.from(name.trim())[0]?.toUpperCase() ?? "?";
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center font-display font-bold", SIZES[size])} style={tileStyle(seed)}>
      {initial}
    </span>
  );
}

/** 官方模板的图标,按 URL 里的 slug 认(模板 id 的下划线换成了连字符)。 */
const WORKFLOW_ICONS: Record<string, LucideIcon> = {
  "full-video-generation": Film,
  "transcript-video-cleanup": Scissors,
  "translated-dub": Languages,
  "highlight-shorts": Smartphone,
  "product-on-model": Shirt,
  "product-pitch-short": ShoppingBag,
  "footage-montage": Clapperboard,
  "fabric-lookbook": Layers,
};

export function WorkflowTile({ slug, cover, size = "md" }: { slug: string; cover?: string | null; size?: keyof typeof SIZES }) {
  if (cover) return <Cover src={cover} size={size} />;
  const Icon = WORKFLOW_ICONS[slug] ?? Workflow;
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center", SIZES[size])} style={tileStyle(slug)}>
      <Icon className={size === "lg" ? "size-7" : "size-5"} strokeWidth={1.8} />
    </span>
  );
}
