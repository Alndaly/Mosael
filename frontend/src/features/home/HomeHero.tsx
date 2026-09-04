import React from "react";
import { BookText, Clapperboard, RefreshCcw } from "lucide-react";

import { useI18n, usePreferences } from "@/app/preferences";
import { holidayOf, seeded, HOLIDAYS, type Holiday } from "@/features/home/holiday";
import type { Poem } from "@/features/home/poems";
import { cn } from "@/lib/utils";

/**
 * 首页顶部:问候 + 走字的钟 + 每日一句,外加节日彩蛋。
 *
 * **彩蛋的分寸**:它铺在问候区背后、`pointer-events-none`、透明度压得很低 —— 首页是每天都
 * 要看的页面,一个抢眼的装饰第三天就变成噪音。平日只有几枚极淡的胶片格子;到了节日才换成
 * 对应的图标并动起来,而"今天是个日子"这件事本身才是被记住的那部分。
 */

const MOTION_CLASS = {
  fall: "animate-holiday-fall",
  rise: "animate-holiday-rise",
  sway: "animate-holiday-sway",
  pulse: "animate-holiday-pulse",
} as const;

function HolidayParticles({ holiday }: { holiday: Holiday }) {
  const { Icon, motion } = holiday;
  const count = motion === "pulse" ? 4 : motion === "sway" ? 5 : 8;
  const color = `var(--holiday-${holiday.accent})`;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {Array.from({ length: count }).map((_, index) => {
        const size = 12 + Math.floor(seeded(index, 3) * 14);
        const duration =
          motion === "fall"
            ? 7 + seeded(index, 4) * 5
            : motion === "rise"
              ? 6 + seeded(index, 4) * 4
              : motion === "pulse"
                ? 2 + seeded(index, 4) * 1.5
                : 3 + seeded(index, 4) * 2;
        return (
          <Icon
            key={index}
            className={cn("absolute opacity-[0.18]", MOTION_CLASS[motion])}
            style={{
              left: `${seeded(index, 1) * 92 + 2}%`,
              top: motion === "rise" ? undefined : `${motion === "pulse" ? seeded(index, 2) * 60 + 8 : 0}%`,
              bottom: motion === "rise" ? 0 : undefined,
              width: size,
              height: size,
              color,
              animationDuration: `${duration}s`,
              // 负延迟 = 一进页面就已经在半途,不会看到八个图标齐刷刷从同一处开始。
              animationDelay: `-${seeded(index, 5) * duration}s`,
            }}
          />
        );
      })}
    </div>
  );
}

/** 平日的底纹:几枚胶片格子。够淡,不看的时候不存在。 */
function IdleDecor() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      <Clapperboard className="absolute -left-1 top-1 size-6 -rotate-12 text-muted-foreground opacity-[0.07]" />
      <Clapperboard className="absolute left-10 bottom-0 size-4 rotate-12 text-muted-foreground opacity-[0.07]" />
      <Clapperboard className="absolute left-1/3 top-0 size-3 text-muted-foreground opacity-[0.06]" />
    </div>
  );
}

export function HomeHero({
  greeting,
  workspaceName,
  now,
  poem,
  poemLoading,
  poemEgg,
  onRefreshPoem,
  holidayOverride,
}: {
  greeting: string;
  workspaceName: string;
  now: Date;
  poem: Poem;
  poemLoading: boolean;
  /** 连翻十次的那个彩蛋文案;非空时代替诗句显示。 */
  poemEgg?: string;
  onRefreshPoem: () => void;
  /** ?holiday=christmas 之类,用来预览节日效果 —— 否则一年只有几天能看到自己写的东西。 */
  holidayOverride?: string | null;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const dateLocale = locale === "en-US" ? "en-US" : "zh-CN";
  const holiday = holidayOverride ? (HOLIDAYS[holidayOverride] ?? null) : holidayOf(now);
  const accent = holiday ? `var(--holiday-${holiday.accent})` : undefined;
  const HolidayIcon = holiday?.Icon;

  return (
    <section className="relative flex items-stretch justify-between gap-2 max-[880px]:flex-col">
      {holiday ? <HolidayParticles holiday={holiday} /> : <IdleDecor />}

      <div className="relative flex min-w-0 flex-col justify-center gap-0.5">
        <h1 className="m-0 flex flex-wrap items-baseline gap-x-2 text-xl font-[650] tracking-[-0.01em]">
          {greeting}
          <span className="text-xs font-normal text-muted-foreground">{workspaceName}</span>
          {holiday && HolidayIcon && (
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-ui-xs font-medium"
              style={{ color: accent, background: `color-mix(in srgb, ${accent} 12%, transparent)` }}
            >
              <HolidayIcon size={11} />
              {t(holiday.labelKey as Parameters<typeof t>[0])}
            </span>
          )}
        </h1>
        <small className="text-xs tabular-nums text-muted-foreground">
          {now.toLocaleDateString(dateLocale, { year: "numeric", month: "long", day: "numeric", weekday: "long" })}
          {"  "}
          {now.toLocaleTimeString(dateLocale, { hour12: false })}
        </small>
      </div>

      {/* 诗卡:一行三格(图标 / 正文 / 刷新),靠 flex 居中 —— 此前图标和按钮是绝对定位钉在
          左上和右上的,两行文字时看着就像被挂在角上。 */}
      <figure
        className="relative m-0 flex max-w-[46ch] items-center gap-2.5 rounded-lg border border-border bg-panel px-2.5 py-2 max-[880px]:max-w-none"
        aria-live="polite"
      >
        <span
          className="grid size-8 shrink-0 place-items-center rounded-md"
          style={{
            color: accent ?? "var(--muted-foreground)",
            background: accent ? `color-mix(in srgb, ${accent} 12%, transparent)` : "var(--secondary)",
          }}
        >
          <BookText size={15} />
        </span>
        <div className="min-w-0 flex-1">
          {poemEgg ? (
            <blockquote className="m-0 text-ui-md leading-normal">{poemEgg}</blockquote>
          ) : (
            <>
              <blockquote className="m-0 line-clamp-2 text-ui-md leading-normal">{poem.text}</blockquote>
              {(poem.author || poem.source) && (
                <figcaption className="mt-0.5 truncate text-ui-xs text-muted-foreground">
                  {[poem.author, poem.source && `《${poem.source}》`].filter(Boolean).join(" · ")}
                </figcaption>
              )}
            </>
          )}
        </div>
        <button
          type="button"
          className="grid size-7 shrink-0 cursor-pointer place-items-center self-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-default"
          aria-label={t("homePoemRefresh")}
          onClick={onRefreshPoem}
          disabled={poemLoading}
        >
          <RefreshCcw size={12} className={poemLoading ? "animate-mosael-spin" : undefined} />
        </button>
      </figure>
    </section>
  );
}
