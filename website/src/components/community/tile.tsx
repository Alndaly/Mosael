import { Clapperboard, Film, Languages, Layers, type LucideIcon, Scissors, Shirt, ShoppingBag, Smartphone } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 社区卡片左上角那块图标。
 *
 * 插件清单里没有图标,硬塞一个通用拼图块的话,一屏卡片长得一模一样,扫一眼分不出谁是谁。
 * 这里用**名字的第一个字**加一个按 id 固定的色相:同一个插件在列表、详情、推荐位上永远是
 * 同一块颜色,认得出来。工作流有明确的用途,用对应的图标(和应用里「工作流社区」同一套)。
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

export function PluginTile({ seed, name, size = "md" }: { seed: string; name: string; size?: keyof typeof SIZES }) {
  // 「Amazon S3」取 A,「腾讯云 COS」取 腾 —— 按字形取,不按 UTF-16 码元。
  const initial = Array.from(name.trim())[0]?.toUpperCase() ?? "?";
  return (
    <span
      aria-hidden
      className={cn("grid shrink-0 place-items-center font-display font-bold", SIZES[size])}
      style={tileStyle(seed)}
    >
      {initial}
    </span>
  );
}

const WORKFLOW_ICONS: Record<string, LucideIcon> = {
  full_video_generation: Film,
  transcript_video_cleanup: Scissors,
  translated_dub: Languages,
  highlight_shorts: Smartphone,
  product_on_model: Shirt,
  product_pitch_short: ShoppingBag,
  footage_montage: Clapperboard,
  fabric_lookbook: Layers,
};

export function WorkflowTile({ id, size = "md" }: { id: string; size?: keyof typeof SIZES }) {
  const Icon = WORKFLOW_ICONS[id] ?? Film;
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center", SIZES[size])} style={tileStyle(id)}>
      <Icon className={size === "lg" ? "size-7" : "size-5"} strokeWidth={1.8} />
    </span>
  );
}
