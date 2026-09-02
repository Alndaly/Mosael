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
  { id: "media-library", image: "/media/home/media-library.webp", width: 3592, height: 2060, href: "/docs/guides/media" },
  { id: "editing", image: "/media/home/editor-showcase.webp", width: 3680, height: 2392, href: "/docs/guides/editing" },
  { id: "agent", image: "/media/screens/dark/ai-chat.png", width: 2880, height: 1520, href: "/docs/guides/ai-studio" },
  { id: "workflows", image: "/media/home/workflows.webp", width: 2400, height: 1401, href: "/workflows" },
] as const;

const CHAPTER_TONES = [
  "bg-[#17141f] text-[#fbf9ff]",
  "bg-[#eee9ff] text-[#18131f] dark:bg-[#211b31] dark:text-foreground",
  "bg-[#f7eaf4] text-[#21141f] dark:bg-[#291b29] dark:text-foreground",
  "bg-[#eaf2ff] text-[#171725] dark:bg-[#171e2d] dark:text-foreground",
  "bg-[#f5efe8] text-[#201814] dark:bg-[#2a211d] dark:text-foreground",
] as const;

function ProductShot({ src, alt, width, height, priority = false }: { src: string; alt: string; width: number; height: number; priority?: boolean }) {
  return (
    <figure className="m-0">
      <Image src={src} alt={alt} width={width} height={height} priority={priority} sizes="(min-width: 1024px) 78vw, 100vw" className="block h-auto w-full" />
    </figure>
  );
}

function PrimaryActions({ download, source, inverted = false }: { download: string; source: string; inverted?: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 lg:justify-start">
      <a href={SITE.releases} target="_blank" rel="noreferrer" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/86 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <Download className="size-4" aria-hidden />
        {download}
      </a>
      <a href={SITE.repo} target="_blank" rel="noreferrer" className={cn("inline-flex min-h-12 items-center justify-center gap-2 rounded-full border px-6 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", inverted ? "border-white/20 text-white hover:bg-white/8" : "border-border/80 bg-paper/40 text-foreground hover:bg-white/50 dark:hover:bg-white/8")}>
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
    <div className="-mt-20 overflow-hidden bg-paper">
      <section id="product" className="relative isolate px-5 pt-40 pb-20 sm:px-8 sm:pt-48 sm:pb-28 lg:px-12">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.26),transparent_36%),radial-gradient(circle_at_84%_12%,rgba(255,139,120,0.25),transparent_32%),linear-gradient(180deg,#f7f3ff_0%,#fff7f5_58%,var(--paper)_100%)] dark:bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.28),transparent_36%),radial-gradient(circle_at_84%_12%,rgba(255,139,120,0.13),transparent_32%),linear-gradient(180deg,#171322_0%,#19131d_58%,var(--paper)_100%)]" />
        <Reveal className="mx-auto flex max-w-5xl flex-col items-center text-center">
          <p className="m-0 inline-flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-primary uppercase"><span className="size-1.5 rounded-full bg-primary" />{t.eyebrow}</p>
          <h1 className="mt-7 mb-0 max-w-[12ch] font-display text-[clamp(3.8rem,9.5vw,8.6rem)] leading-[0.88] font-[720] tracking-[-0.065em] text-balance">{t.titleLead} <span className="bg-gradient-to-r from-[#5a43ea] via-[#a74fec] to-[#ff8b78] bg-clip-text text-transparent">{t.titleAccent}</span></h1>
          <p className="mt-8 mb-0 max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg sm:leading-8">{t.lede}</p>
          <div className="mt-9"><PrimaryActions download={t.ctaDownload} source={t.ctaSource} /></div>
          <p className="mt-5 mb-0 text-xs leading-5 text-muted-foreground">{t.platforms}</p>
        </Reveal>
        <Reveal className="relative mx-auto mt-16 max-w-[92rem] sm:mt-20" delay={90}>
          <div className="pointer-events-none absolute -inset-x-20 top-1/4 bottom-0 -z-10 bg-[radial-gradient(ellipse_at_center,rgba(114,87,233,0.2),rgba(255,161,190,0.12)_44%,transparent_72%)]" />
          <ProductShot src="/media/home/editor-showcase.webp" alt={t.heroShotAlt} width={3680} height={2392} priority />
        </Reveal>
      </section>

      <section className="px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <Reveal className="mx-auto grid max-w-[84rem] gap-10 lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.storyEyebrow}</p><h2 className="mt-5 mb-0 max-w-[13ch] font-display text-[clamp(2.8rem,6vw,5.8rem)] leading-[0.96] font-[700] tracking-[-0.055em] text-balance">{t.storyTitle}</h2></div>
          <p className="m-0 max-w-xl text-base leading-8 text-muted-foreground lg:col-span-5 lg:pb-1">{t.storyBody}</p>
        </Reveal>
      </section>

      <section>
        {t.chapters.map((chapter, index) => {
          const config = CHAPTERS[index];
          const dark = index === 0;
          const reverse = index % 2 === 1;
          return (
            <article id={config.id} key={config.id} className={cn("relative overflow-hidden py-20 sm:py-28", CHAPTER_TONES[index])}>
              <span className={cn("pointer-events-none absolute -top-10 right-4 font-display text-[clamp(11rem,24vw,22rem)] leading-none font-bold tracking-[-0.09em]", dark ? "text-white/[0.035]" : "text-current/[0.035]")}>{String(index + 1).padStart(2, "0")}</span>
              <Reveal className="relative mx-auto grid max-w-[88rem] gap-12 px-5 sm:px-8 lg:grid-cols-12 lg:items-center lg:px-12">
                <div className={cn("lg:col-span-5", reverse && "lg:order-2 lg:pl-8")}>
                  <p className={cn("m-0 text-xs font-bold tracking-[0.16em] uppercase", dark ? "text-[#b9a9ff]" : "text-primary")}>{String(index + 1).padStart(2, "0")} / {chapter.label}</p>
                  <h3 className="mt-5 mb-0 max-w-[13ch] font-display text-[clamp(2.7rem,5vw,5rem)] leading-[0.94] font-[710] tracking-[-0.055em] text-balance">{chapter.title}</h3>
                  <p className={cn("mt-7 mb-0 max-w-lg text-base leading-8", dark ? "text-white/60" : "text-current/60")}>{chapter.body}</p>
                  <ul className="mt-7 mb-0 grid list-none gap-2 p-0 text-sm">{chapter.points.map((point) => <li key={point} className="flex items-center gap-3"><span className={cn("h-px w-5", dark ? "bg-white/28" : "bg-current/25")} />{point}</li>)}</ul>
                  <Link href={localePath(locale, config.href)} className={cn("mt-8 inline-flex items-center gap-2 text-sm font-semibold transition-opacity hover:opacity-70", dark ? "text-[#c9beff]" : "text-primary")}>{chapter.cta}<ArrowRight className="size-4" aria-hidden /></Link>
                </div>
                <div className={cn("lg:col-span-7", reverse && "lg:order-1")}><ProductShot src={config.image} alt={chapter.shotAlt} width={config.width} height={config.height} /></div>
              </Reveal>
            </article>
          );
        })}
      </section>

      <section className="bg-[#17141f] px-5 py-24 text-[#fbf9ff] sm:px-8 sm:py-32 lg:px-12">
        <Reveal className="mx-auto grid max-w-[84rem] gap-14 lg:grid-cols-12 lg:items-start">
          <div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-[#b9a9ff] uppercase">{t.localEyebrow}</p><h2 className="mt-5 mb-0 max-w-[12ch] font-display text-[clamp(3rem,7vw,6.5rem)] leading-[0.93] font-[710] tracking-[-0.06em] text-balance">{t.localTitle}</h2><p className="mt-7 mb-0 max-w-xl text-base leading-8 text-white/62">{t.localBody}</p></div>
          <ol className="m-0 grid list-none p-0 lg:col-span-5">{t.localPoints.map((point, index) => <li key={point.title} className="grid grid-cols-[2.5rem_1fr] gap-4 border-t border-white/12 py-6 first:border-t-0 lg:first:border-t"><span className="font-mono text-xs text-[#b9a9ff]">0{index + 1}</span><div><strong className="block font-display text-xl font-semibold tracking-[-0.02em]">{point.title}</strong><span className="mt-2 block text-sm leading-6 text-white/55">{point.body}</span></div></li>)}</ol>
        </Reveal>
      </section>

      <section className="px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="mx-auto max-w-[84rem]">
          <Reveal className="grid gap-10 lg:grid-cols-12 lg:items-end"><div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.moreEyebrow}</p><h2 className="mt-5 mb-0 max-w-[13ch] font-display text-[clamp(2.8rem,6vw,5.6rem)] leading-[0.96] font-[700] tracking-[-0.055em] text-balance">{t.moreTitle}</h2></div><p className="m-0 text-sm leading-7 text-muted-foreground lg:col-span-5">{t.moreBody}</p></Reveal>
          <div className="mt-16 grid border-t border-border md:grid-cols-2">{t.more.map((item, index) => <Reveal key={item.title} delay={index * 80} className="group flex min-h-64 flex-col border-b border-border py-10 md:px-10 md:first:border-r md:first:pl-0"><span className="font-mono text-xs tracking-[0.14em] text-primary/55">0{index + 1}</span><h3 className="mt-auto mb-0 font-display text-3xl font-semibold tracking-[-0.035em]">{item.title}</h3><p className="mt-4 mb-0 max-w-[34em] text-sm leading-7 text-muted-foreground">{item.body}</p><Link href={localePath(locale, item.href)} className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-primary">{item.cta}<ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden /></Link></Reveal>)}</div>
        </div>
      </section>

      <section className="bg-[linear-gradient(125deg,#eee9ff_0%,#f9edf5_52%,#fff4e8_100%)] px-5 py-20 text-[#1a1520] sm:px-8 sm:py-28 lg:px-12 dark:bg-[linear-gradient(125deg,#211b31_0%,#291b29_52%,#2d211c_100%)] dark:text-foreground">
        <Reveal className="mx-auto grid max-w-[84rem] gap-12 lg:grid-cols-12 lg:items-center"><div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.makerEyebrow}</p><h2 className="mt-4 mb-0 max-w-[13ch] font-display text-[clamp(2.5rem,5vw,4.8rem)] leading-[0.98] font-[700] tracking-[-0.05em]">{t.makerTitle}</h2><p className="mt-6 mb-0 max-w-xl text-sm leading-7 text-current/62">{t.makerBody}</p></div><div className="flex items-center gap-5 lg:col-span-5 lg:justify-end"><BrandIcon size={72} className="rounded-[1.4rem]" /><div><p className="m-0 font-display text-2xl font-semibold tracking-[-0.025em]">KindaHuaX</p><a href={SITE.authorX} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:opacity-70">{t.makerX}<ArrowRight className="size-4" aria-hidden /></a></div></div></Reveal>
      </section>

      <section className="bg-[#17141f] px-5 py-24 text-center text-[#fbf9ff] sm:px-8 sm:py-36">
        <Reveal className="mx-auto flex max-w-5xl flex-col items-center"><BrandWordmark className="w-32" /><h2 className="mt-10 mb-0 max-w-[12ch] font-display text-[clamp(3rem,7vw,6.5rem)] leading-[0.92] font-[710] tracking-[-0.06em] text-balance">{t.closingTitle}</h2><p className="mt-6 mb-0 max-w-xl text-base leading-8 text-white/60">{t.closingBody}</p><div className="mt-9"><PrimaryActions download={t.ctaDownload} source={t.ctaSource} inverted /></div><p className="mt-5 mb-0 text-xs text-white/42">{t.platforms}</p></Reveal>
      </section>
    </div>
  );
}
