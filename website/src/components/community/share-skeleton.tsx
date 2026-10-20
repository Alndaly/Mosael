import { getMessages } from "@/i18n/messages";
import type { Locale } from "@/i18n/config";

const SKELETON_GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

/** 分享列表的骨架。首屏 / 换筛选项 / 换页时都显示它,版面不会跳一下。 */
export function ShareListSkeleton({ locale, count = 6 }: { locale: Locale; count?: number }) {
  const t = getMessages(locale).community;
  return (
    <div>
      <output className="sr-only">{t.loadingShares}</output>
      <div className={SKELETON_GRID} aria-hidden>
        {Array.from({ length: count }, (_, index) => (
          <div key={index} className="grid gap-4 rounded-2xl border border-border bg-card p-5">
            <div className="flex items-center gap-3.5">
              <div className="size-12 shrink-0 rounded-xl bg-muted" />
              <div className="grid flex-1 gap-2">
                <div className="h-4 w-3/4 rounded bg-muted" />
                <div className="h-3 w-1/3 rounded bg-muted" />
              </div>
            </div>
            <div className="grid gap-2">
              <div className="h-3 w-full rounded bg-muted" />
              <div className="h-3 w-5/6 rounded bg-muted" />
              <div className="h-3 w-2/3 rounded bg-muted" />
            </div>
            <div className="h-4 w-2/5 rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
