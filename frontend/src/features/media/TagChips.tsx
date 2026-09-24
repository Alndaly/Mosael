import { cn } from "@/lib/utils";

/**
 * 素材上的标签,只露前几个,其余收成「+N」(悬停看全部)。
 *
 * 素材库的卡片和剪辑页素材面板的每一行都用它 —— 露几个、怎么收、收起来的去哪看,两处一个样。
 * `tone` 只管底色:`overlay` 叠在缩略图上(深底浅字,压得住任何画面),`surface` 放在面板里
 * 的文字行旁边。
 */
export function TagChips({ tags, max = 2, tone, className }: {
  tags: readonly string[];
  max?: number;
  tone: "overlay" | "surface";
  className?: string;
}) {
  if (tags.length === 0) return null;
  const shown = tags.slice(0, max);
  const rest = tags.slice(max);
  const chip = cn(
    "rounded-sm px-[5px] py-px text-ui-2xs leading-4",
    tone === "overlay" ? "bg-[rgba(10,12,15,0.72)] text-[#e8eaed]" : "bg-secondary text-muted-foreground",
  );
  return (
    <span className={cn("flex min-w-0 gap-1", className)} data-asset-tags>
      {shown.map((tag) => (
        <span key={tag} className={cn(chip, "min-w-0 max-w-full truncate")} title={tag}>
          {tag}
        </span>
      ))}
      {rest.length > 0 && <span className={cn(chip, "shrink-0 tabular-nums")} title={rest.join(", ")}>+{rest.length}</span>}
    </span>
  );
}
