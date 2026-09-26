import { useI18n } from "@/app/preferences";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/**
 * 统计窗口「7 / 30 / 90 天」—— 统计页和管理页是**同一个**控件、同一套取值,两页上的「近 N 天」
 * 是同一个意思。上限和后端 `domain/dashboard.MAX_WINDOW_DAYS` 一致:再长就是在扫全库了。
 */
const RANGES = ["7", "30", "90"] as const;
type Range = (typeof RANGES)[number];

/** 选中的窗口(天),按页记住。`key` 每页一个(如 "admin-range")。 */
export function useStatRange(key: string): [number, (days: number) => void] {
  const [range, setRange] = usePersistentTab<Range>(key, "30", RANGES);
  return [Number(range), (days) => setRange(String(days) as Range)];
}

export function RangePicker({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  const t = useI18n();
  return (
    <span className={cn(SEGMENTED_LIST, "min-h-8 p-0.5")} role="radiogroup" aria-label={t("statRangeLabel")}>
      {RANGES.map((value) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={Number(value) === days}
          className={cn(segmentedTriggerClass(Number(value) === days), "min-h-7 px-3 text-ui-xs tabular-nums")}
          onClick={() => onChange(Number(value))}
        >
          {t("statRangeDays").replace("{n}", value)}
        </button>
      ))}
    </span>
  );
}
