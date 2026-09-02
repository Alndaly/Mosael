import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Download } from "lucide-react";

import { BrandIcon, BrandWordmark } from "@/components/brand-logo";
import { GithubMark } from "@/components/icons";
import { Reveal } from "@/components/reveal";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";
import { cn } from "@/lib/utils";

const CHAPTERS = [
  { id: "infinite-canvas", image: "/media/home/infinite-canvas.webp", width: 2400, height: 1552, href: "/docs/guides/boards" },
  { id: "editing", image: "/media/home/editor.webp", width: 2400, height: 1560, href: "/docs/guides/editing" },
  { id: "agent", image: "/media/screens/dark/ai-chat.png", width: 2880, height: 1520, href: "/docs/guides/ai-studio" },
  { id: "workflows", image: "/media/home/workflows.webp", width: 2400, height: 1401, href: "/workflows" },
] as const;

function ProductShot({ src, alt, width, height, priority = false, className }: { src: string; alt: string; width: number; height: number; priority?: boolean; className?: string }) {
  return (
    <figure className={cn("m-0 overflow-hidden rounded-[1.35rem] border border-border/70 bg-[#15131d]", className)}>
      <Image src={src} alt={alt} width={width} height={height} priority={priority} sizes="(min-width: 1024px) 64vw, 100vw" className="block h-auto w-full" />
    </figure>
  );
}

function PrimaryActions({ download, source, compact = false }: { download: string; source: string; compact?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <a href={SITE.releases} target="_blank" rel="noreferrer" className={cn("inline-flex items-center justify-center gap-2 rounded-lg bg-primary font-semibold text-primary-foreground transition-colors hover:bg-primary/88 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", compact ? "min-h-10 px-4 text-sm" : "min-h-12 px-5 text-[0.9375rem]")}>
        <Download className="size-4" aria-hidden />
        {download}
      </a>
      <a href={SITE.repo} target="_blank" rel="noreferrer" className={cn("inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-background font-semibold text-foreground transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", compact ? "min-h-10 px-4 text-sm" : "min-h-12 px-5 text-[0.9375rem]")}>
        <GithubMark className="size-4" />
        {source}
      </a>
    </div>
  );
}

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).home;

  return (
    <div className="overflow-hidden bg-paper">
      <section id="product" className="relative border-b border-border/60">
        <div className="mx-auto grid max-w-[90rem] gap-14 px-5 pt-20 pb-20 sm:px-8 sm:pt-24 lg:grid-cols-12 lg:items-center lg:gap-10 lg:px-12 lg:pt-28 lg:pb-24">
          <Reveal className="lg:col-span-4">
            <p className="m-0 text-xs font-semibold tracking-[0.16em] text-primary uppercase">{t.eyebrow}</p>
            <h1 className="mt-6 mb-0 max-w-[11ch] font-display text-[clamp(3.25rem,6.4vw,6.6rem)] leading-[0.94] font-[720] tracking-[-0.055em] text-balance">
              {t.titleLead} <span className="text-primary">{t.titleAccent}</span>
            </h1>
            <p className="mt-8 mb-0 max-w-[32em] text-base leading-7 text-muted-foreground sm:text-[1.0625rem]">{t.lede}</p>
            <div className="mt-9"><PrimaryActions download={t.ctaDownload} source={t.ctaSource} /></div>
            <p className="mt-5 mb-0 text-xs leading-5 text-muted-foreground">{t.platforms}</p>
          </Reveal>

          <Reveal delay={100} className="lg:col-span-8 lg:pl-4">
            <ProductShot src="/media/home/overview.webp" alt={t.heroShotAlt} width={2400} height={1552} priority />
          </Reveal>
        </div>
      </section>

      <section className="relative isolate border-b border-border/60">
        <Image src="/media/home/timeline-path.webp" alt="" width={837} height={1880} aria-hidden className="pointer-events-none absolute top-[8%] left-1/2 -z-10 hidden h-[84%] w-[48rem] -translate-x-1/2 object-fill opacity-65 lg:block dark:hidden" />
        <div className="mx-auto max-w-[90rem] px-5 py-24 sm:px-8 sm:py-28 lg:px-12 lg:py-36">
          <div className="flex flex-col gap-28 sm:gap-36 lg:gap-44">
            {t.chapters.map((chapter, index) => {
              const config = CHAPTERS[index];
              const copyOnRight = index % 2 === 1;
              return (
                <Reveal as="article" key={config.id} className="grid gap-10 lg:grid-cols-12 lg:items-center lg:gap-x-14">
                  <div className={cn("lg:col-span-4", copyOnRight ? "lg:order-2 lg:col-start-9" : "lg:col-start-1")}>
                    <div className="flex items-start gap-5">
                      <span className="font-display text-[clamp(3.5rem,6vw,5.75rem)] leading-none font-semibold tracking-[-0.06em] text-primary/35">{String(index + 1).padStart(2, "0")}</span>
                      <div className="pt-2 sm:pt-3">
                        <p className="m-0 text-[0.6875rem] font-bold tracking-[0.16em] text-primary uppercase">{chapter.label}</p>
                        <h2 className="mt-4 mb-0 font-display text-[clamp(2rem,4vw,3.35rem)] leading-[1.04] font-[680] tracking-[-0.04em] text-balance">{chapter.title}</h2>
                      </div>
                    </div>
                    <p className="mt-6 mb-0 max-w-[31em] text-[0.9375rem] leading-7 text-muted-foreground">{chapter.body}</p>
                    <ul className="mt-6 mb-0 grid list-disc gap-2.5 pl-5 text-sm leading-6 text-foreground/82 marker:text-primary">
                      {chapter.points.map((point) => <li key={point}>{point}</li>)}
                    </ul>
                    <Link href={localePath(locale, config.href)} className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-primary transition-colors hover:text-primary/75">
                      {chapter.cta}<ArrowRight className="size-4" aria-hidden />
                    </Link>
                  </div>
                  <div className={cn("lg:col-span-8", copyOnRight ? "lg:order-1 lg:col-start-1" : "lg:col-start-5")}>
                    <ProductShot src={config.image} alt={chapter.shotAlt} width={config.width} height={config.height} />
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      <section className="border-b border-border/60 bg-brand-soft">
        <Reveal className="mx-auto grid max-w-[90rem] gap-10 px-5 py-16 sm:px-8 lg:grid-cols-12 lg:items-center lg:px-12 lg:py-20">
          <div className="lg:col-span-6">
            <p className="m-0 text-xs font-semibold tracking-[0.16em] text-primary uppercase">{t.localEyebrow}</p>
            <h2 className="mt-4 mb-0 font-display text-[clamp(2rem,4vw,3.4rem)] leading-[1.04] font-[680] tracking-[-0.04em]">{t.localTitle}</h2>
            <p className="mt-5 mb-0 max-w-[38em] text-[0.9375rem] leading-7 text-muted-foreground">{t.localBody}</p>
          </div>
          <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-3 lg:col-span-6">
            {t.localPoints.map((point) => (
              <li key={point.title} className="border-l-2 border-primary/45 pl-4"><strong className="block text-sm font-semibold">{point.title}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{point.body}</span></li>
            ))}
          </ul>
        </Reveal>
      </section>

      <section className="border-b border-border/60">
        <div className="mx-auto max-w-[90rem] px-5 py-20 sm:px-8 lg:px-12 lg:py-24">
          <Reveal className="grid gap-8 lg:grid-cols-[minmax(14rem,0.8fr)_repeat(2,minmax(0,1fr))] lg:gap-0">
            <div className="pr-8"><p className="m-0 text-xs font-semibold tracking-[0.16em] text-primary uppercase">{t.moreEyebrow}</p><h2 className="mt-4 mb-0 font-display text-3xl leading-tight font-[660] tracking-[-0.035em]">{t.moreTitle}</h2></div>
            {t.more.map((item, index) => (
              <div key={item.title} className={cn("border-t border-border/60 pt-6 lg:border-t-0 lg:border-l lg:px-8 lg:pt-0", index === 1 && "lg:pr-0")}>
                <h3 className="m-0 font-display text-xl font-semibold tracking-[-0.02em]">{item.title}</h3>
                <p className="mt-3 mb-0 max-w-[31em] text-sm leading-6 text-muted-foreground">{item.body}</p>
                <Link href={localePath(locale, item.href)} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:text-primary/75">{item.cta}<ArrowRight className="size-4" aria-hidden /></Link>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      <section className="border-b border-border/60">
        <Reveal className="mx-auto grid max-w-[90rem] gap-8 px-5 py-16 sm:px-8 lg:grid-cols-12 lg:items-center lg:px-12 lg:py-20">
          <div className="lg:col-span-7"><p className="m-0 text-xs font-semibold tracking-[0.16em] text-primary uppercase">{t.makerEyebrow}</p><h2 className="mt-4 mb-0 font-display text-[clamp(2rem,4vw,3.4rem)] leading-[1.04] font-[680] tracking-[-0.04em]">{t.makerTitle}</h2><p className="mt-5 mb-0 max-w-[38em] text-[0.9375rem] leading-7 text-muted-foreground">{t.makerBody}</p></div>
          <div className="flex items-center gap-5 lg:col-span-5 lg:justify-end"><BrandIcon size={64} className="rounded-2xl" /><div><p className="m-0 font-display text-xl font-semibold tracking-[-0.02em]">KindaHuaX</p><a href={SITE.authorX} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:text-primary/75">{t.makerX}<ArrowRight className="size-4" aria-hidden /></a></div></div>
        </Reveal>
      </section>

      <section className="border-b border-border/60 bg-brand-soft">
        <Reveal className="mx-auto grid max-w-[90rem] gap-8 px-5 py-16 sm:px-8 lg:grid-cols-12 lg:items-center lg:px-12 lg:py-20">
          <div className="lg:col-span-6"><h2 className="m-0 font-display text-[clamp(2.25rem,5vw,4.25rem)] leading-[0.98] font-[700] tracking-[-0.05em] text-balance">{t.closingTitle}</h2><p className="mt-5 mb-0 max-w-xl text-[0.9375rem] leading-7 text-muted-foreground">{t.closingBody}</p></div>
          <div className="lg:col-span-6 lg:justify-self-end"><PrimaryActions download={t.ctaDownload} source={t.ctaSource} compact /><p className="mt-4 mb-0 text-xs text-muted-foreground lg:text-right">{t.platforms}</p></div>
        </Reveal>
      </section>

      <div className="mx-auto flex max-w-[90rem] items-center justify-between gap-8 px-5 py-8 sm:px-8 lg:px-12"><BrandWordmark className="w-28" /><p className="m-0 text-right text-xs leading-5 text-muted-foreground">{t.bottomLine}</p></div>
    </div>
  );
}
