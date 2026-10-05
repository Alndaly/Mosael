import type { Metadata } from "next";
import { HomeShowcase, type ShowcaseWindow } from "@/components/home-showcase";
import { mediaVersion } from "@/lib/media";
import { Shot } from "@/components/shot";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Download } from "lucide-react";

import { BrandIcon, BrandWordmark } from "@/components/brand-logo";
import { GithubMark } from "@/components/icons";
import { JsonLd } from "@/components/json-ld";
import { QrCards } from "@/components/qr-cards";
import { PointerSurface, TiltCard } from "@/components/pointer-motion";
import { StarField } from "@/components/star-field";
import { Reveal } from "@/components/reveal";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { DownloadLink } from "@/components/download-link";
import { getMessages } from "@/i18n/messages";
import { listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";
import { SITE } from "@/lib/site";
import { faqLd, organizationLd, softwareApplicationLd, websiteLd } from "@/lib/structured-data";
import { cn } from "@/lib/utils";

/**
 * 首页的章节按「读者会搜什么」排:AI 生成、ComfyUI、剪辑与配音、数字人与译配、工作流,然后才是
 * 画布和 3D。每章配一张实拍截图(public/media,深浅两套由 Shot 切);文案在 messages.ts 的
 * `home.chapters`,顺序与这里一一对应。
 */
const CHAPTERS = [
  { id: "ai-generation", image: "/media/screens/ai-generate-models.png", href: "/docs/guides/ai-studio" },
  { id: "comfyui", image: "/media/screens/model-library.png", href: "/docs/guides/comfyui" },
  { id: "editing", image: "/media/screens/subtitle-dub.png", href: "/docs/guides/editing" },
  { id: "digital-humans", image: "/media/screens/entity-speak.png", href: "/docs/guides/digital-humans" },
  { id: "workflows", image: "/media/screens/workflows.png", href: "/docs/guides/workflows" },
  { id: "infinite-canvas", image: "/media/screens/boards.png", href: "/docs/guides/boards" },
  { id: "3d-scenes", image: "/media/homepage/zh/scenes.png", href: "/docs/guides/scenes" },
] as const;

const CHAPTER_TONES = [
  "bg-[#17141f] text-[#fbf9ff]",
  "bg-[#e7f1f2] text-[#152b30] dark:bg-[#18282c] dark:text-foreground",
  "bg-[#eee9ff] text-[#18131f] dark:bg-[#211b31] dark:text-foreground",
  "bg-[#f7eaf4] text-[#21141f] dark:bg-[#291b29] dark:text-foreground",
  "bg-[#eaf2ff] text-[#171725] dark:bg-[#171e2d] dark:text-foreground",
  "bg-[#f5efe8] text-[#201814] dark:bg-[#2a211d] dark:text-foreground",
  "bg-[#ecf3ea] text-[#16231a] dark:bg-[#19241c] dark:text-foreground",
] as const;

/** 章节截图按语言取:英文那套在 `screens/en/`、`homepage/en/`。 */
function chapterImage(locale: Locale, image: string): string {
  return locale === "en" ? image.replace("/screens/", "/screens/en/").replace("/homepage/zh/", "/homepage/en/") : image;
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  // 解构而不是 `meta.description`:inline-markdown 的棘轮把「x.description 直接进 meta」当成数据泄漏,
  // 而这几句是 messages.ts 里手写的文案。
  const { title, description, keywords } = getMessages(locale).meta;
  return pageMetadata({ locale, path: "", title, description, keywords });
}

function ProductShot({ src, alt, priority = false }: { src: string; alt: string; priority?: boolean }) {
  return (
    <TiltCard>
      <Shot src={src} alt={alt} priority={priority} framed />
    </TiltCard>
  );
}

function PrimaryActions({ locale, download, source, inverted = false }: { locale: Locale; download: string; source: string; inverted?: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 lg:justify-start">
      <DownloadLink locale={locale} className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/86 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <Download className="size-4" aria-hidden />
        {download}
      </DownloadLink>
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
  const messages = getMessages(locale);
  const t = messages.home;
  const windows: ShowcaseWindow[] = (["boards", "editor", "scenes"] as const).map((id) => {
    const src = `/media/homepage/${locale}/${id}.png`;
    return { id, src: `${src}?v=${mediaVersion(src)}`, ...t.showcase[id],
      href: localePath(locale, `/docs/guides/${id === "editor" ? "editing" : id}`) };
  });
  // 模板卡片只列目录里真有的那几个(测试也盯着 slug 都在):模板改名或下架时,首页不出死链。
  const catalog = new Set(listWorkflows(locale).map((workflow) => workflow.slug));
  const templates = t.templates.filter((template) => catalog.has(template.slug));

  const { description, keywords } = messages.meta;
  const structured = [
    organizationLd(),
    websiteLd(description),
    softwareApplicationLd({
      locale,
      description,
      features: t.chapters.map((chapter) => `${chapter.label}: ${chapter.title}`),
      screenshots: CHAPTERS.map((chapter) => chapterImage(locale, chapter.image)),
      keywords,
    }),
    faqLd(t.faq),
  ];

  return (
    <div className="-mt-20 overflow-hidden bg-paper">
      <JsonLd data={structured} />
      <PointerSurface as="section" id="product" className="relative isolate px-5 pt-32 pb-16 sm:px-8 sm:pt-36 sm:pb-24 lg:px-12">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.26),transparent_36%),radial-gradient(circle_at_84%_12%,rgba(255,139,120,0.25),transparent_32%),linear-gradient(180deg,#f7f3ff_0%,#fff7f5_58%,var(--paper)_100%)] dark:bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.28),transparent_36%),radial-gradient(circle_at_84%_12%,rgba(255,139,120,0.13),transparent_32%),linear-gradient(180deg,#171322_0%,#19131d_58%,var(--paper)_100%)]" />
        {/* 一层星点:慢慢明灭,鼠标附近的几颗亮一点、轻轻让开,划过时偶尔落几颗星屑。在内容下面一层,不挡点击。 */}
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
          <StarField />
        </div>
        <Reveal className="mx-auto flex max-w-5xl flex-col items-center text-center">
          <p className="m-0 inline-flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-primary uppercase"><span className="size-1.5 rounded-full bg-primary" />{t.eyebrow}</p>
          {/* 整页唯一的 h1。标题带着读者会搜的词(AI 视频生成 / 剪辑 / 配音),字号比口号时代收了一档:字多了。
              前后两半各占一行(各自 text-balance):连成一段排的话,中文会在「配|音」中间折行。 */}
          <h1 className="mt-7 mb-0 max-w-5xl font-display text-[clamp(2.4rem,5.2vw,5rem)] leading-[1.02] font-[720] tracking-[-0.05em]"><span className="block text-balance">{t.titleLead}</span> <span className="block bg-gradient-to-r from-[#5a43ea] via-[#a74fec] via-60% to-[#ff8b78] bg-[length:200%_auto] bg-clip-text text-balance text-transparent motion-safe:animate-gradient-pan">{t.titleAccent}</span></h1>
          <p className="mt-8 mb-0 max-w-3xl text-base leading-7 text-muted-foreground sm:text-lg sm:leading-8">{t.lede}</p>
          <div className="mt-9"><PrimaryActions locale={locale} download={t.ctaDownload} source={t.ctaSource} /></div>
          <p className="mt-5 mb-0 text-xs leading-5 text-muted-foreground">{t.platforms}</p>
        </Reveal>
        <Reveal className="relative mx-auto mt-10 max-w-[92rem] sm:mt-12" delay={90}>
          <div className="pointer-events-none absolute -inset-x-20 top-1/4 bottom-0 -z-10 bg-[radial-gradient(ellipse_at_center,rgba(114,87,233,0.2),rgba(255,161,190,0.12)_44%,transparent_72%)]" />
          <HomeShowcase windows={windows} label={t.showcaseLabel} explore={t.showcaseExplore} />
        </Reveal>
      </PointerSurface>

      <section className="px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <Reveal className="mx-auto grid max-w-[84rem] gap-10 lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.storyEyebrow}</p><h2 className="mt-5 mb-0 max-w-[14ch] font-display text-[clamp(2.6rem,5.5vw,5.2rem)] leading-[0.98] font-[700] tracking-[-0.055em] text-balance">{t.storyTitle}</h2></div>
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
              <span aria-hidden className={cn("pointer-events-none absolute -top-10 right-4 font-display motion-safe:animate-[number-drift_linear_both] motion-safe:[animation-range:entry_0%_exit_100%] motion-safe:[animation-timeline:view()] text-[clamp(11rem,24vw,22rem)] leading-none font-bold tracking-[-0.09em]", dark ? "text-white/[0.035]" : "text-current/[0.035]")}>{String(index + 1).padStart(2, "0")}</span>
              <Reveal className="relative mx-auto grid max-w-[88rem] gap-12 px-5 sm:px-8 lg:grid-cols-12 lg:items-center lg:px-12">
                <div className={cn("lg:col-span-5", reverse && "lg:order-2 lg:pl-8")}>
                  <p className={cn("m-0 text-xs font-bold tracking-[0.16em] uppercase", dark ? "text-[#b9a9ff]" : "text-primary")}>{String(index + 1).padStart(2, "0")} / {chapter.label}</p>
                  <h3 className="mt-5 mb-0 max-w-[16ch] font-display text-[clamp(2.3rem,4.2vw,4.2rem)] leading-[0.98] font-[710] tracking-[-0.05em] text-balance">{chapter.title}</h3>
                  <p className={cn("mt-7 mb-0 max-w-lg text-base leading-8", dark ? "text-white/60" : "text-current/60")}>{chapter.body}</p>
                  <ul className="mt-7 mb-0 grid list-none gap-2 p-0 text-sm">{chapter.points.map((point) => <li key={point} className="flex items-center gap-3"><span className={cn("h-px w-5 shrink-0", dark ? "bg-white/28" : "bg-current/25")} />{point}</li>)}</ul>
                  <Link href={localePath(locale, config.href)} className={cn("mt-8 inline-flex items-center gap-2 text-sm font-semibold transition-opacity hover:opacity-70", dark ? "text-[#c9beff]" : "text-primary")}>{chapter.cta}<ArrowRight className="size-4" aria-hidden /></Link>
                </div>
                <div className={cn("lg:col-span-7", reverse && "lg:order-1")}><ProductShot src={chapterImage(locale, config.image)} alt={chapter.shotAlt} /></div>
              </Reveal>
            </article>
          );
        })}
      </section>

      <section id="templates" className="px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="mx-auto max-w-[84rem]">
          <Reveal className="grid gap-10 lg:grid-cols-12 lg:items-end"><div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.templatesEyebrow}</p><h2 className="mt-5 mb-0 max-w-[13ch] font-display text-[clamp(2.8rem,6vw,5.6rem)] leading-[0.96] font-[700] tracking-[-0.055em] text-balance">{t.templatesTitle}</h2></div><p className="m-0 text-sm leading-7 text-muted-foreground lg:col-span-5">{t.templatesBody}</p></Reveal>
          <ul className="mt-16 grid list-none gap-px overflow-hidden rounded-2xl border border-border bg-border p-0 sm:grid-cols-2 lg:grid-cols-4">
            {templates.map((template) => (
              <li key={template.slug} className="bg-paper">
                <Link href={localePath(locale, `/workflows/${template.slug}`)} className="group flex h-full flex-col gap-3 p-6 transition-colors hover:bg-secondary/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring">
                  <h3 className="m-0 font-display text-xl font-semibold tracking-[-0.02em] text-balance group-hover:text-primary">{template.title}</h3>
                  <p className="m-0 text-sm leading-6 text-muted-foreground">{template.body}</p>
                </Link>
              </li>
            ))}
          </ul>
          <Link href={localePath(locale, "/workflows")} className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:opacity-70">{t.templatesCta}<ArrowRight className="size-4" aria-hidden /></Link>
        </div>
      </section>

      <section id="models" className="bg-[#f3f0fb] px-5 py-24 sm:px-8 sm:py-32 lg:px-12 dark:bg-[#1b1726]">
        <div className="mx-auto max-w-[84rem]">
          <Reveal className="grid gap-10 lg:grid-cols-12 lg:items-end"><div className="lg:col-span-7"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.modelsEyebrow}</p><h2 className="mt-5 mb-0 max-w-[14ch] font-display text-[clamp(2.6rem,5.5vw,5.2rem)] leading-[0.98] font-[700] tracking-[-0.055em] text-balance">{t.modelsTitle}</h2></div><p className="m-0 text-sm leading-7 text-muted-foreground lg:col-span-5">{t.modelsBody}</p></Reveal>
          <dl className="mt-14 grid gap-8 md:grid-cols-2 lg:grid-cols-3">
            {t.modelGroups.map((group) => (
              <div key={group.label}>
                <dt className="font-display text-lg font-semibold tracking-[-0.02em]">{group.label}</dt>
                <dd className="m-0 mt-4">
                  <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                    {group.models.map((model) => <li key={model} className="rounded-full border border-border bg-paper/70 px-3 py-1.5 text-sm">{model}</li>)}
                  </ul>
                </dd>
              </div>
            ))}
          </dl>
          <Link href={localePath(locale, "/docs/guides/providers")} className="mt-12 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:opacity-70">{t.modelsCta}<ArrowRight className="size-4" aria-hidden /></Link>
        </div>
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
          <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-border bg-border md:grid-cols-2 lg:grid-cols-3">{t.more.map((card, index) => <div key={card.title} className="group flex min-h-64 flex-col bg-paper p-8 sm:p-10"><span className="font-mono text-xs tracking-[0.14em] text-primary/55">0{index + 1}</span><h3 className="mt-auto mb-0 pt-8 font-display text-2xl font-semibold tracking-[-0.035em]">{card.title}</h3><p className="mt-4 mb-0 max-w-[34em] text-sm leading-7 text-muted-foreground">{card.body}</p><Link href={localePath(locale, card.href)} className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-primary">{card.cta}<ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden /></Link></div>)}</div>
        </div>
      </section>

      {/* 常见问题。答案全部展开、写在服务端 HTML 里:FAQPage 结构化数据要求问答在页面上看得见,
          而「是不是开源」「要不要显卡」正是读者会直接搜的问题。 */}
      <section id="faq" className="border-t border-border px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
        <div className="mx-auto grid max-w-[84rem] gap-14 lg:grid-cols-12">
          <div className="lg:col-span-4"><p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.faqEyebrow}</p><h2 className="mt-5 mb-0 max-w-[10ch] font-display text-[clamp(2.6rem,5vw,4.8rem)] leading-[0.98] font-[700] tracking-[-0.055em] text-balance">{t.faqTitle}</h2></div>
          <div className="grid gap-x-12 gap-y-10 lg:col-span-8 md:grid-cols-2">
            {t.faq.map((entry) => (
              <div key={entry.question}>
                <h3 className="m-0 font-display text-lg font-semibold tracking-[-0.015em]">{entry.question}</h3>
                <p className="mt-3 mb-0 text-sm leading-7 text-muted-foreground">{entry.answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[linear-gradient(125deg,#eee9ff_0%,#f9edf5_52%,#fff4e8_100%)] px-5 py-20 text-[#1a1520] sm:px-8 sm:py-28 lg:px-12 dark:bg-[linear-gradient(125deg,#211b31_0%,#291b29_52%,#2d211c_100%)] dark:text-foreground">
        <Reveal className="mx-auto grid max-w-[84rem] gap-14 lg:grid-cols-12 lg:items-start">
          <div className="lg:col-span-5 lg:sticky lg:top-28">
            <p className="m-0 text-xs font-bold tracking-[0.16em] text-primary uppercase">{t.makerEyebrow}</p>
            <h2 className="mt-4 mb-0 max-w-[13ch] font-display text-[clamp(2.5rem,5vw,4.8rem)] leading-[0.98] font-[700] tracking-[-0.05em]">{t.makerTitle}</h2>
            <p className="mt-6 mb-0 max-w-xl text-sm leading-7 text-current/62">{t.makerBody}</p>
            <div className="mt-9 flex items-center gap-5">
              <BrandIcon size={72} className="rounded-[1.4rem]" />
              <div>
                <p className="m-0 font-display text-2xl font-semibold tracking-[-0.025em]">KindaHuaX</p>
                <a href={SITE.authorX} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:opacity-70">{t.makerX}<ArrowRight className="size-4" aria-hidden /></a>
              </div>
            </div>
          </div>
          <QrCards
            group={t.makerGroup}
            groupHint={t.makerGroupHint}
            author={t.makerWechat}
            authorHint={t.makerWechatHint}
            className="m-0 lg:col-span-7"
          />
        </Reveal>
      </section>

      <section className="bg-[#17141f] px-5 py-24 text-center text-[#fbf9ff] sm:px-8 sm:py-36">
        <Reveal className="mx-auto flex max-w-5xl flex-col items-center"><BrandWordmark className="w-32" /><h2 className="mt-10 mb-0 max-w-[14ch] font-display text-[clamp(3rem,7vw,6.5rem)] leading-[0.92] font-[710] tracking-[-0.06em] text-balance">{t.closingTitle}</h2><p className="mt-6 mb-0 max-w-xl text-base leading-8 text-white/60">{t.closingBody}</p><div className="mt-9"><PrimaryActions locale={locale} download={t.ctaDownload} source={t.ctaSource} inverted /></div><p className="mt-5 mb-0 text-xs text-white/42">{t.platforms}</p></Reveal>
      </section>
    </div>
  );
}
