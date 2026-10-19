import Image from "next/image";
import Link from "next/link";
import { Check, LockKeyhole } from "lucide-react";

import { BrandWordmark } from "@/components/brand-logo";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

/**
 * 注册 / 登录 / 账号三页共用的版式。
 *
 * 视觉方向是「暗房 + 一束光」:左侧仍是站点那张暖白的纸,只放表单;右侧是一块固定的
 * 深色工作台,一束紫光落在 Mosael 的真实剪辑截图上。它回答的是「我在登录什么」——
 * 不是又一张飘在空白里的卡片。移动端收成一列:先表单,再产品叙事。
 */
export function AccountShell({
  locale,
  copy,
  title,
  lede,
  wide = false,
  children,
}: {
  locale: Locale;
  copy: Messages["account"];
  title: string;
  lede: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  const shot = locale === "en" ? "/media/homepage/en/editor.png" : "/media/homepage/zh/editor.png";
  const points = [copy.studioPointLocal, copy.studioPointModels, copy.studioPointTimeline];

  return (
    <section className="relative bg-paper">
      <div className="mx-auto grid min-w-0 max-w-[96rem] lg:min-h-[calc(100svh-5rem)] lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <div className="relative flex min-w-0 flex-col px-5 pt-10 pb-14 sm:px-8 sm:pt-14 lg:px-12 lg:py-14 xl:px-20">
          <div
            className={cn(
              "mx-auto flex w-full min-w-0 flex-1 flex-col",
              wide ? "max-w-[38rem]" : "max-w-[31rem]",
              "lg:mx-0",
            )}
          >
            <Link
              href={`/${locale}`}
              aria-label="Mosael"
              className="inline-flex w-fit items-center gap-3 rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
            >
              <BrandWordmark className="w-24 sm:w-28" priority />
              <span className="h-4 w-px bg-border" aria-hidden />
              <span className="rounded-full border border-border bg-card/70 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                Cloud
              </span>
            </Link>

            <div className="flex flex-1 flex-col justify-center py-10 motion-safe:animate-[auth-rise_650ms_ease-out_both] lg:py-16">
              <h1 className="m-0 font-display text-[clamp(2.15rem,4.2vw,3.55rem)] leading-[1.02] font-semibold tracking-[-0.045em] text-balance">
                {title}
              </h1>
              <p className="mt-5 mb-0 max-w-[38ch] text-[15px] leading-7 text-muted-foreground text-pretty sm:text-base">
                {lede}
              </p>
              <div className="mt-8">{children}</div>
            </div>

            <p className="m-0 flex items-start gap-2 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">
              <LockKeyhole className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
              {copy.cloudNote}
            </p>
          </div>
        </div>

        <aside
          aria-label={copy.studioEyebrow}
          className="relative isolate flex min-w-0 flex-col overflow-x-clip bg-[#0b0812] text-[#f5f1f8]"
        >
          <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute -top-[26%] left-[34%] h-[125%] w-[42%] rotate-[18deg] bg-[linear-gradient(180deg,rgba(185,169,255,0.38),rgba(255,139,120,0.09)_48%,transparent_72%)] blur-3xl" />
            <div className="absolute -top-[16%] left-[48%] h-[92%] w-[12%] rotate-[18deg] bg-[linear-gradient(180deg,rgba(255,255,255,0.14),transparent_70%)] blur-2xl" />
            <div className="absolute -right-24 top-20 size-96 rounded-full bg-[radial-gradient(circle,rgba(114,87,233,0.38),transparent_68%)] blur-2xl" />
            <div className="absolute inset-x-0 bottom-0 h-1/2 bg-[linear-gradient(180deg,transparent,rgba(8,6,12,0.72))]" />
          </div>

          <div className="relative flex flex-col justify-between gap-10 px-5 py-10 sm:px-8 sm:py-12 lg:sticky lg:top-20 lg:h-[calc(100svh-5rem)] lg:px-10 lg:py-14 xl:px-16">
            <p className="m-0 inline-flex items-center gap-2 text-[13px] font-medium text-[#c7c1d2] motion-safe:animate-[auth-rise_650ms_ease-out_both]">
              <span className="size-1.5 rounded-full bg-[#b9a9ff] shadow-[0_0_18px_rgba(185,169,255,0.9)]" aria-hidden />
              {copy.studioEyebrow}
            </p>

            <figure className="m-0 motion-safe:animate-[auth-rise_800ms_ease-out_90ms_both]">
              <div className="relative mx-auto max-w-[42rem]">
                <div
                  aria-hidden
                  className="absolute -inset-10 -z-10 rounded-[3rem] bg-[radial-gradient(ellipse_at_center,rgba(114,87,233,0.3),transparent_70%)] blur-2xl"
                />
                <div className="overflow-hidden rounded-2xl border border-white/15 bg-[#09070d] p-1.5 shadow-[0_40px_120px_-28px_rgba(0,0,0,0.92)] sm:p-2">
                  <div aria-hidden className="flex h-7 items-center gap-1.5 px-2">
                    <span className="size-1.5 rounded-full bg-white/20" />
                    <span className="size-1.5 rounded-full bg-white/14" />
                    <span className="size-1.5 rounded-full bg-white/10" />
                    <span className="ml-2 truncate font-mono text-[10px] text-[#8f889b]">mosael / timeline</span>
                  </div>
                  <Image
                    src={shot}
                    alt={copy.studioShotAlt}
                    width={2880}
                    height={1880}
                    sizes="(max-width: 1023px) 100vw, 52vw"
                    className="block h-auto w-full rounded-[0.65rem]"
                  />
                </div>
              </div>
              <figcaption className="mx-auto mt-7 max-w-[32rem] text-center text-[13px] leading-6 text-[#c7c1d2]">
                {copy.studioCaption}
              </figcaption>
            </figure>

            <div className="max-w-[38rem] motion-safe:animate-[auth-rise_800ms_ease-out_180ms_both]">
              <h2 className="m-0 max-w-[20ch] font-display text-[clamp(1.8rem,2.8vw,2.9rem)] leading-[1.04] font-semibold tracking-[-0.045em] text-[#f5f1f8] text-balance">
                {copy.studioTitle}
              </h2>
              <p className="mt-4 mb-0 max-w-[34rem] text-[14px] leading-7 text-[#c7c1d2] text-pretty">{copy.studioBody}</p>
              <ul className="m-0 mt-6 flex list-none flex-wrap gap-x-5 gap-y-2.5 p-0 text-xs text-[#aaa2b2]">
                {points.map((point) => (
                  <li key={point} className="inline-flex items-center gap-1.5">
                    <Check className="size-3.5 text-[#b9a9ff]" aria-hidden />
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
