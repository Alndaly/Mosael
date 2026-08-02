import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowLeft, ArrowRight } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { DocsToc } from "@/components/docs-toc";
import { mdxComponents } from "@/components/mdx";
import { LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { docHref, listDocs, readDoc } from "@/lib/docs";
import { tableOfContents } from "@/lib/toc";
import { SITE } from "@/lib/site";

/** 24 页 × 2 语言,全部构建期出好 —— 文档是纯静态内容,没有理由到运行时才渲染。 */
export function generateStaticParams() {
  return LOCALES.flatMap((locale) =>
    listDocs(locale).map((doc) => ({
      locale,
      section: doc.section,
      name: doc.name,
    })),
  );
}

type Params = Promise<{ locale: string; section: string; name: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, section, name } = await params;
  if (!isLocale(locale)) return {};
  const doc = readDoc(locale, section, name);
  if (!doc) return {};
  const canonical = `/${locale}/docs/${section}/${name}`;
  return {
    title: `${doc.title} · Open Studio`,
    description: doc.description,
    alternates: {
      canonical,
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
  const sectionLabel = t.sections[doc.section];
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

  const toc = tableOfContents(doc.body);
  const all = listDocs(locale);
  const index = all.findIndex((item) => item.section === section && item.name === name);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;

  return (
    // 正文和本页目录并排。目录是这一页自己的东西(骨架拿不到 doc),所以留在页面里。
    <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_14rem] xl:gap-10">
      <article className="min-w-0 max-w-3xl">
        <header className="mb-12 border-b-2 border-ink pb-8">
          <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">{sectionLabel}</p>
          <h1 className="mt-0 mb-4 font-display text-[clamp(1.875rem,5vw,3rem)] leading-[1.05] font-extrabold tracking-[-0.02em]">
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

      <aside className="mt-14 border-t-2 border-ink pt-8 xl:mt-0 xl:border-t-0 xl:border-l-2 xl:pt-0 xl:pl-8">
        <DocsToc entries={toc} label={t.onThisPage} />
      </aside>
    </div>
  );
}
