import Image from "next/image";
import { notFound } from "next/navigation";
import { ArrowRight, BookOpen, Puzzle, Send } from "lucide-react";

import { Marquee } from "@/components/marquee";
import { Reveal } from "@/components/reveal";
import { Shot } from "@/components/shot";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";
import { cn } from "@/lib/utils";

/**
 * 首页只讲一件事:本地优先的 AI 视频工作台。
 *
 * 版面按**整幅色带**切开 —— 纸、墨、朱轮流铺满整个宽度,段与段之间是一条 2px 的硬边。
 * 不用卡片网格:七张一样大的卡片等于什么都没强调,而色带自己就说清了"这是新的一段"。
 *
 * 三段叙述(剪辑 / 智能体 / 工作流)各配一张真实界面,左右交替。知识库、发布、插件收在
 * 末尾的"还有"里 —— 它们是补充,不是并列的主角。
 *
 * 文案全在 `@/i18n/messages`:JSX 会把源码换行折成空格,中文里那是凭空多出来的字距,
 * 只在浏览器里看得见。这里只留结构。
 */

/**
 * 与 `messages.home.chapters` 一一对应 —— 文案在那边,图在这边,按顺序配对。
 *
 * 只写路径,尺寸由 `Shot` 从文件头读:重录一次换了分辨率,这里不用跟着改。
 */
const CHAPTER_SHOTS = ["/media/gifs/timeline-edit.gif", "/media/screens/ai-chat.png", "/media/screens/workflows.png"];

/** 「还有」那三条的图标与顶条颜色,同样按顺序配对。 */
const MORE_MARKS = [
  { icon: BookOpen, bar: "bg-flame" },
  { icon: Send, bar: "bg-indigo" },
  { icon: Puzzle, bar: "bg-ink" },
];

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).home;

  return (
    <>
      {/* ── 首屏:纸 ──────────────────────────────────────────────────────────
          标题占满版心,底下压着一整张界面 —— 一屏之内把"这是什么"和"长什么样"都给完。 */}
      <section className="border-b-2 border-ink bg-paper bg-rule bg-[size:80px_80px]">
        <div className="mx-auto max-w-[96rem] px-5 pt-20 pb-16 sm:px-8 sm:pt-28">
          <Reveal className="max-w-5xl">
            <p className="m-0 inline-flex items-center gap-2.5 border-2 border-ink bg-card px-3 py-1.5 font-mono text-xs font-bold tracking-widest uppercase">
              <span className="size-2 bg-flame" />
              {t.eyebrow}
            </p>

            <h1 className="mt-8 mb-0 font-display text-[clamp(2.75rem,9vw,7.5rem)] leading-[0.92] font-extrabold tracking-[-0.03em]">
              {t.titleLead}
              <br />
              <span className="mt-2 inline-block bg-flame px-3 text-primary-foreground sm:mt-4">{t.titleAccent}</span>
            </h1>

            <p className="mt-10 mb-0 max-w-2xl text-lg text-muted-foreground sm:text-xl">{t.lede}</p>

            <div className="mt-10 flex flex-wrap items-center gap-4">
              <a
                href={SITE.releases}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-3 border-2 border-ink bg-flame px-7 py-4 text-base font-bold text-primary-foreground shadow-block transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-none"
              >
                {t.ctaDownload}
                <ArrowRight className="size-5" />
              </a>
              <a
                href={SITE.repo}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center border-2 border-ink px-7 py-4 text-base font-bold transition-colors hover:bg-ink hover:text-paper"
              >
                {t.ctaSource}
              </a>
              <span className="font-mono text-xs tracking-wider text-muted-foreground uppercase">{t.platforms}</span>
            </div>
          </Reveal>

          <Reveal delay={120} className="mt-16 sm:mt-20">
            {/* 不写死宽高:Shot 会从 public/ 下的文件头读真实尺寸。写死的后果是重录一次
                换了分辨率,比例就对不上,图被纵向拉伸 —— 而且只在浏览器里看得出来。 */}
            <Shot src="/media/screens/editor.png" alt={t.heroShotAlt} caption={t.heroShotCaption} framed priority />
          </Reveal>
        </div>
      </section>

      <Marquee items={t.marquee} />

      {/* ── 三章:墨 ────────────────────────────────────────────────────────── */}
      <section className="border-b-2 border-ink bg-invert text-invert-foreground">
        <div className="mx-auto max-w-[96rem] px-5 py-24 sm:px-8 sm:py-32">
          <Reveal>
            <h2 className="mt-0 mb-20 max-w-4xl font-display text-[clamp(1.75rem,5vw,3.75rem)] leading-[1.05] font-extrabold tracking-[-0.02em]">
              {t.chaptersTitle}
            </h2>
          </Reveal>

          <div className="flex flex-col gap-24 sm:gap-32">
            {t.chapters.map((chapter, index) => {
              const shot = CHAPTER_SHOTS[index];
              // 左右交替。三段同一个方向排下来像一张清单,交替之后才有翻页的节奏。
              const flipped = index % 2 === 1;
              return (
                <Reveal as="article" key={chapter.label} className="lg:grid lg:grid-cols-12 lg:items-center lg:gap-16">
                  <div className={cn("lg:col-span-5", flipped && "lg:order-2 lg:col-start-8")}>
                    <p className="m-0 flex items-baseline gap-4 font-mono text-xs font-bold tracking-widest uppercase">
                      <span className="font-display text-5xl leading-none text-flame">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      {chapter.label}
                    </p>
                    <h3 className="mt-6 mb-5 font-display text-2xl font-bold tracking-tight sm:text-4xl">
                      {chapter.title}
                    </h3>
                    <p className="m-0 max-w-(--measure) text-invert-foreground/70">{chapter.body}</p>
                  </div>
                  <div className={cn("mt-10 lg:col-span-7 lg:mt-0", flipped && "lg:order-1 lg:col-start-1")}>
                    <Shot src={shot} alt={chapter.shotAlt} framed />
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── 本地优先:朱 ──────────────────────────────────────────────────────
          全站唯一一处主张,给它一整幅最烈的颜色 —— 撞色就该用在有话要说的地方。 */}
      <section className="border-b-2 border-ink bg-flame text-primary-foreground">
        <div className="mx-auto max-w-[96rem] px-5 py-24 sm:px-8 sm:py-32">
          <Reveal className="lg:grid lg:grid-cols-12 lg:gap-16">
            <h2 className="mt-0 mb-8 font-display text-[clamp(1.75rem,5vw,3.5rem)] leading-[1.05] font-extrabold tracking-[-0.02em] lg:col-span-5 lg:mb-0">
              {t.localTitle}
            </h2>
            <div className="lg:col-span-7">
              {t.localBody.map((paragraph) => (
                <p key={paragraph} className="mt-0 mb-6 text-lg last:mb-0">
                  {paragraph}
                </p>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── 还有:纸 ────────────────────────────────────────────────────────── */}
      <section className="border-b-2 border-ink bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-24 sm:px-8 sm:py-32">
          <Reveal>
            <h2 className="mt-0 mb-14 font-display text-[clamp(1.75rem,5vw,3.5rem)] leading-none font-extrabold tracking-[-0.02em]">
              {t.moreTitle}
            </h2>
          </Reveal>
          <div className="grid gap-8 sm:grid-cols-3">
            {t.more.map((item, index) => {
              const { icon: Icon, bar } = MORE_MARKS[index];
              return (
                <Reveal
                  key={item.title}
                  delay={index * 80}
                  className="border-2 border-ink bg-card transition-transform hover:-translate-y-1"
                >
                  <div className={cn("h-2.5", bar)} />
                  <div className="p-7">
                    <Icon className="mb-6 size-6" aria-hidden />
                    <h3 className="mt-0 mb-3 font-display text-xl font-bold tracking-tight">{item.title}</h3>
                    <p className="m-0 text-muted-foreground">{item.body}</p>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── 社区:纸 ────────────────────────────────────────────────────────
          两张二维码。放在收尾 CTA **之前** —— 下载完就走的人不会再往下滚,而"想找个人问问"
          恰恰发生在决定下载之前。 */}
      <section className="border-b-2 border-ink bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-24 sm:px-8 sm:py-32">
          <Reveal className="lg:grid lg:grid-cols-12 lg:items-center lg:gap-16">
            <div className="lg:col-span-5">
              <h2 className="mt-0 mb-6 font-display text-[clamp(1.75rem,5vw,3.5rem)] leading-[1.05] font-extrabold tracking-[-0.02em]">
                {t.communityTitle}
              </h2>
              <p className="m-0 max-w-(--measure) text-lg text-muted-foreground">{t.communityBody}</p>
            </div>

            <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:col-span-7 lg:mt-0">
              {[
                { src: "/media/qr-group.png", title: t.communityGroup, hint: t.communityGroupHint },
                { src: "/media/qr-wechat.png", title: t.communityAuthor, hint: t.communityAuthorHint },
              ].map((card) => (
                <figure key={card.src} className="m-0 flex flex-col border-2 border-ink bg-card">
                  {/* 两张二维码原图的比例和底色都不一样(一张 2:3 深底,一张 4:5 白底)。
                      固定同一个画框 + object-contain:两张卡因此一样高、说明文字也对得齐,
                      而二维码本身一个像素都没被裁掉 —— 裁了就扫不出来。 */}
                  <div className="relative aspect-4/5 w-full border-b-2 border-ink bg-secondary">
                    <Image
                      src={card.src}
                      alt={card.title}
                      fill
                      sizes="(min-width: 64rem) 22rem, 45vw"
                      className="object-contain"
                    />
                  </div>
                  <figcaption className="p-5">
                    <p className="m-0 font-display text-lg font-bold tracking-tight">{card.title}</p>
                    <p className="m-0 mt-1 text-sm text-muted-foreground">{card.hint}</p>
                  </figcaption>
                </figure>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── 收尾:墨 ────────────────────────────────────────────────────────── */}
      <section className="bg-invert text-invert-foreground">
        <div className="mx-auto max-w-[96rem] px-5 py-24 sm:px-8 sm:py-32">
          <Reveal>
            <h2 className="mt-0 mb-6 max-w-3xl font-display text-[clamp(2rem,6vw,4.5rem)] leading-[1.02] font-extrabold tracking-[-0.03em]">
              {t.closingTitle}
            </h2>
            <p className="mt-0 mb-10 max-w-xl text-lg text-invert-foreground/70">{t.closingBody}</p>
            <div className="flex flex-wrap items-center gap-4">
              <a
                href={SITE.releases}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-3 border-2 border-invert-foreground bg-flame px-7 py-4 text-base font-bold text-primary-foreground transition-transform hover:-translate-y-1"
              >
                {t.ctaDownload}
                <ArrowRight className="size-5" />
              </a>
              <span className="font-mono text-xs tracking-wider text-invert-foreground/60 uppercase">
                {t.platforms}
              </span>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
