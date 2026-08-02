import { notFound } from "next/navigation";

import { Shot } from "@/components/shot";
import { Button } from "@/components/ui/button";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 首页只讲一件事:本地优先的 AI 视频工作台。
 *
 * 所以不是七个模块平铺成七张卡,而是三段叙述 —— 剪辑、智能体、工作流 —— 每段配一张
 * 真实界面的图。知识库 / 发布 / 插件收在末尾一小节里,它们是"还有",不是并列的主角。
 *
 * 文案全在 `@/i18n/messages`:JSX 会把源码换行折成空格,中文里那是凭空多出来的字距,
 * 只在浏览器里看得见。这里只留结构。
 */

/** 与 `messages.home.chapters` 一一对应 —— 文案在那边,图在这边,按顺序配对。 */
const CHAPTER_SHOTS = [
  { src: "/media/gifs/timeline-edit.gif", width: 880, height: 550 },
  { src: "/media/screens/ai-chat.png", width: 2880, height: 1520 },
  { src: "/media/screens/workflows.png", width: 2880, height: 1520 },
];

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).home;

  return (
    <div className="prose-cn mx-auto max-w-5xl px-6 font-serif sm:px-8">
      <section className="pt-20 pb-16 sm:pt-28">
        <p className="m-0 font-sans text-sm tracking-wide text-muted-foreground">{t.eyebrow}</p>
        <h1 className="mt-5 mb-0 text-4xl font-semibold sm:text-6xl">{t.title}</h1>
        <p className="mt-7 mb-0 text-lg text-muted-foreground sm:text-xl">{t.lede}</p>
        <div className="mt-9 flex flex-wrap items-center gap-3 font-sans">
          <Button asChild size="lg" className="h-11 px-5 text-base">
            <a href={SITE.releases} target="_blank" rel="noreferrer">
              {t.ctaDownload}
            </a>
          </Button>
          <Button asChild variant="outline" size="lg" className="h-11 px-5 text-base">
            <a href={SITE.repo} target="_blank" rel="noreferrer">
              {t.ctaSource}
            </a>
          </Button>
        </div>
        <p className="mt-6 mb-0 font-sans text-sm text-muted-foreground">{t.platforms}</p>
      </section>

      <Shot
        src="/media/screens/editor.png"
        alt={t.heroShotAlt}
        width={1920}
        height={1200}
        caption={t.heroShotCaption}
        priority
      />

      <section className="pt-28">
        <h2 className="mt-0 mb-16 text-2xl font-semibold sm:text-3xl">{t.chaptersTitle}</h2>
        <div className="flex flex-col gap-24">
          {t.chapters.map((chapter, index) => {
            const shot = CHAPTER_SHOTS[index];
            return (
              <article key={chapter.label}>
                <p className="m-0 font-sans text-sm tracking-wide text-muted-foreground">{chapter.label}</p>
                <h3 className="mt-3 mb-4 text-xl font-semibold sm:text-2xl">{chapter.title}</h3>
                <p className="mt-0 mb-8">{chapter.body}</p>
                <Shot src={shot.src} alt={chapter.shotAlt} width={shot.width} height={shot.height} />
              </article>
            );
          })}
        </div>
      </section>

      <section className="pt-28">
        <h2 className="mt-0 mb-6 text-2xl font-semibold sm:text-3xl">{t.localTitle}</h2>
        {t.localBody.map((paragraph) => (
          <p key={paragraph} className="mt-0 mb-5 last:mb-0">
            {paragraph}
          </p>
        ))}
      </section>

      <section className="pt-24">
        <h2 className="mt-0 mb-8 text-2xl font-semibold sm:text-3xl">{t.moreTitle}</h2>
        {/* 三条并列信息,用发丝分隔线而不是三张卡 —— 卡片会把"还有"抬成和上面三章一样重。 */}
        <dl className="m-0 border-t border-border/60">
          {t.more.map((item) => (
            <div key={item.title} className="border-b border-border/60 py-5 sm:flex sm:gap-8">
              <dt className="font-sans font-medium sm:w-40 sm:shrink-0">{item.title}</dt>
              <dd className="m-0 mt-2 text-muted-foreground sm:mt-0">{item.body}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="pt-24 pb-4">
        <h2 className="mt-0 mb-4 text-2xl font-semibold sm:text-3xl">{t.closingTitle}</h2>
        <p className="mt-0 mb-8">{t.closingBody}</p>
        <div className="flex flex-wrap items-center gap-3 font-sans">
          <Button asChild size="lg" className="h-11 px-5 text-base">
            <a href={SITE.releases} target="_blank" rel="noreferrer">
              {t.ctaDownload}
            </a>
          </Button>
          <span className="text-sm text-muted-foreground">{t.platforms}</span>
        </div>
      </section>
    </div>
  );
}
