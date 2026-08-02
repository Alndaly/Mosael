import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowLeft, ArrowRight } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { DocsSidebar, type SidebarGroup } from "@/components/docs-sidebar";
import { DocsToc } from "@/components/docs-toc";
import { mdxComponents } from "@/components/mdx";
import { LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { DOC_SECTIONS, docHref, listDocs, readDoc } from "@/lib/docs";
import { SITE } from "@/lib/site";
import { tableOfContents } from "@/lib/toc";

/** 24 页 × 2 语言,全部构建期出好 —— 文档是纯静态内容,没有理由到运行时才渲染。 */
export function generateStaticParams() {
  return LOCALES.flatMap((locale) => listDocs(locale).map((doc) => ({ locale, section: doc.section, name: doc.name })));
}

type Params = Promise<{ locale: string; section: string; name: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, section, name } = await params;
  if (!isLocale(locale)) return {};
  const doc = readDoc(locale, section, name);
  if (!doc) return {};
  return {
    title: `${doc.title} · Open Studio`,
    description: doc.description,
    alternates: {
      canonical: `/${locale}/docs/${section}/${name}`,
      languages: Object.fromEntries(LOCALES.map((item) => [item, `/${item}/docs/${section}/${name}`])),
    },
  };
}

/**
 * 一篇文档。
 *
 * **三栏在同一个 grid 里**,不拆成 layout + page 两层 —— 拆开时两个网格各算各的列宽,
 * 中间那栏对不上外层的轨道,于是正文被挤成窄窄一条,而分栏的竖线吊在半空。
 * 侧边栏要的目录树这一页本来就要读,合在一起没有多余开销。
 *
 * 列之间也不画贯穿整页的竖线:导航只有十来行,正文有好几屏,那条线剩下的大半截旁边什么
 * 都没有。分栏靠间距,归属靠每一项自己左边那道短线。
 */
export default async function DocPage({ params }: { params: Params }) {
  const { locale, section, name } = await params;
  if (!isLocale(locale)) notFound();
  const doc = readDoc(locale, section, name);
  if (!doc) notFound();

  const t = getMessages(locale).docs;
  const { content } = await compileMDX({
    source: doc.body,
    components: mdxComponents,
    options: {
      mdxOptions: {
        // gfm:表格和删除线,文档里两样都在用。
        remarkPlugins: [remarkGfm],
        // 标题带 id,才能从别处链到某一节。
        rehypePlugins: [rehypeSlug],
      },
    },
  });

  const all = listDocs(locale);
  const groups: SidebarGroup[] = DOC_SECTIONS.map((key) => ({
    label: t.sections[key],
    items: all
      .filter((item) => item.section === key)
      .map((item) => ({ href: docHref(locale, item), title: item.title })),
  })).filter((group) => group.items.length > 0);

  const toc = tableOfContents(doc.body);
  const index = all.findIndex((item) => item.section === section && item.name === name);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;

  return (
    // `pt-12` 和两侧的 `top-sticky` 是**配套**的(见 globals.css 里 --spacing-sticky 的算式):
    // 侧栏一开始就停在它粘住的位置上,于是滚动时不会先往上滑一小段再顿住。
    <div className="mx-auto grid max-w-[88rem] gap-x-14 gap-y-12 px-5 pt-12 pb-20 sm:px-8 lg:grid-cols-[13rem_minmax(0,1fr)] xl:grid-cols-[13rem_minmax(0,1fr)_13rem]">
      {/* sticky 要直接挂在 grid item 上,并且配 `self-start`:grid 默认把子项拉伸到整行高,
          被拉满的元素在自己的格子里没有可滑动的余量,`position: sticky` 就完全不起作用。 */}
      <DocsSidebar
        groups={groups}
        className="lg:sticky lg:top-sticky lg:col-start-1 lg:row-start-1 lg:max-h-[calc(100svh-9rem)] lg:self-start lg:overflow-y-auto"
      />

      {/* 本页目录在窄屏上排到正文前面 —— 那时它是"这一页讲了什么"的摘要,读完之后才给没有意义。 */}
      <DocsToc
        entries={toc}
        label={t.onThisPage}
        className="xl:sticky xl:top-sticky xl:col-start-3 xl:row-start-1 xl:max-h-[calc(100svh-9rem)] xl:self-start xl:overflow-y-auto"
      />

      <article className="min-w-0 lg:col-start-2 lg:row-start-1">
        <header className="mb-12 border-b-2 border-ink pb-8">
          <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">
            {t.sections[doc.section]}
          </p>
          <h1 className="mt-0 mb-4 font-display text-[clamp(1.875rem,4vw,3rem)] leading-[1.05] font-extrabold tracking-[-0.02em]">
            {doc.title}
          </h1>
          {doc.description && <p className="m-0 text-lg text-muted-foreground">{doc.description}</p>}
        </header>

        <div className="docs-body">{content}</div>

        <footer className="mt-20">
          <div className="grid border-2 border-ink sm:grid-cols-2">
            {prev ? (
              <Link
                className="flex items-center gap-3 border-ink p-6 transition-colors not-last:border-b-2 hover:bg-ink hover:text-paper sm:not-last:border-r-2 sm:not-last:border-b-0"
                href={docHref(locale, prev)}
              >
                <ArrowLeft className="size-5 shrink-0" />
                <span>
                  <span className="block font-mono text-xs font-bold tracking-widest uppercase opacity-60">
                    {t.prev}
                  </span>
                  <span className="font-display font-bold">{prev.title}</span>
                </span>
              </Link>
            ) : (
              <span className="hidden sm:block" />
            )}
            {next && (
              <Link
                className="flex items-center justify-end gap-3 border-t-2 border-ink p-6 text-right transition-colors hover:bg-ink hover:text-paper sm:border-t-0"
                href={docHref(locale, next)}
              >
                <span>
                  <span className="block font-mono text-xs font-bold tracking-widest uppercase opacity-60">
                    {t.next}
                  </span>
                  <span className="font-display font-bold">{next.title}</span>
                </span>
                <ArrowRight className="size-5 shrink-0" />
              </Link>
            )}
          </div>
          <p className="mt-8 mb-0 text-xs">
            <a
              className="border-b-2 border-flame pb-0.5 font-bold"
              href={`${SITE.repo}/blob/main/website/content/docs/${locale as Locale}/${section}/${name}.mdx`}
              target="_blank"
              rel="noreferrer"
            >
              {t.editOnGitHub}
            </a>
          </p>
        </footer>
      </article>
    </div>
  );
}
