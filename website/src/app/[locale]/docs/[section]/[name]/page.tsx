import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowLeft, ArrowRight } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { DocsSidebar, type SidebarGroup } from "@/components/docs-sidebar";
import { DocsMobileNav } from "@/components/docs-mobile-nav";
import { DOC_GROUPS } from "@/lib/docs-navigation";
import { DocsToc } from "@/components/docs-toc";
import { mdxComponents } from "@/components/mdx";
import { LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { docHref, listDocs, readDoc } from "@/lib/docs";
import { SITE } from "@/lib/site";
import { tableOfContents } from "@/lib/toc";

/** Generate every localized guide from the content directory. */
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
    title: `${doc.title} · Mosael`,
    description: doc.description,
    alternates: {
      canonical: `/${locale}/docs/${section}/${name}`,
      languages: Object.fromEntries(LOCALES.map((item) => [item, `/${item}/docs/${section}/${name}`])),
    },
  };
}

export default async function DocPage({ params }: { params: Params }) {
  const { locale, section, name } = await params;
  if (!isLocale(locale)) notFound();
  const doc = readDoc(locale, section, name);
  if (!doc) notFound();

  const t = getMessages(locale).docs;
  const { content } = await compileMDX({
    source: doc.body,
    components: mdxComponents(locale),
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
  const groups: SidebarGroup[] = DOC_GROUPS.map((group) => ({
    label: t.groups[group.id],
    items: group.pages.flatMap((page) => {
      const item = all.find((doc) => `${doc.section}/${doc.name}` === page);
      return item ? [{ href: docHref(locale, item), title: item.title }] : [];
    }),
  }));
  const currentGroup = DOC_GROUPS.find((group) => (group.pages as readonly string[]).includes(`${section}/${name}`));

  const toc = tableOfContents(doc.body);
  const index = all.findIndex((item) => item.section === section && item.name === name);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;

  return (
    <div className="mx-auto grid max-w-[88rem] gap-x-10 gap-y-6 px-5 pt-0 pb-16 xl:pt-12 sm:px-8 lg:grid-cols-[13rem_minmax(0,1fr)] xl:grid-cols-[13rem_minmax(0,1fr)_13rem]">
      <DocsMobileNav groups={groups} entries={toc} labels={t} />
      {/* sticky 要直接挂在 grid item 上,并且配 `self-start`:grid 默认把子项拉伸到整行高,
          被拉满的元素在自己的格子里没有可滑动的余量,`position: sticky` 就完全不起作用。 */}
      <DocsSidebar
        groups={groups}
        label={t.allDocs}
        className="lg:sticky lg:top-sticky lg:col-start-1 lg:row-start-1 lg:row-span-2 lg:pt-6 xl:pt-0 lg:max-h-[calc(100svh-9rem)] lg:self-start lg:overflow-y-auto"
      />

      {/* 本页目录在窄屏上排到正文前面 —— 那时它是"这一页讲了什么"的摘要,读完之后才给没有意义。 */}
      <DocsToc
        entries={toc}
        label={t.onThisPage}
        className="xl:sticky xl:top-sticky xl:col-start-3 xl:row-start-1 xl:max-h-[calc(100svh-9rem)] xl:self-start xl:overflow-y-auto"
      />

      <article className="min-w-0 lg:col-start-2 lg:row-start-2 xl:row-start-1">
        <header className="relative mb-8 border-b border-border pb-6 sm:mb-10 sm:pb-8">
          <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">
            {currentGroup ? t.groups[currentGroup.id] : t.sections[doc.section]}
          </p>
          <h1 className="mt-0 mb-4 max-w-[14ch] font-display text-[clamp(2rem,4.5vw,3.75rem)] leading-[1.1] font-[700] tracking-[-0.05em]">
            {doc.title}
          </h1>
          {doc.description && <p className="m-0 text-base leading-relaxed text-muted-foreground sm:text-lg">{doc.description}</p>}
          {doc.version && <p className="mt-5 mb-0 text-xs text-muted-foreground">{t.reviewed} {doc.version} · {doc.updated}</p>}
        </header>

        <div className="docs-body">{content}</div>

        <p className="mt-10 text-xs text-muted-foreground"><Link href={`/${locale}/docs/about/project#media-credits`}>{t.mediaCredits}</Link></p>

        <footer className="mt-20">
          <div className="grid border-t border-border sm:grid-cols-2">
            {prev ? (
              <Link
                className="flex items-center gap-3 border-border py-6 transition-colors not-last:border-b hover:text-primary sm:px-6 sm:first:pl-0 sm:not-last:border-r sm:not-last:border-b-0"
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
                className="flex items-center justify-end gap-3 border-t border-border py-6 text-right transition-colors hover:text-primary sm:border-t-0 sm:px-6 sm:last:pr-0"
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
              className="font-semibold text-primary hover:opacity-70"
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
