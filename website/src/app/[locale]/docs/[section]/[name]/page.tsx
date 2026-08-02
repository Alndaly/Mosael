import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowLeft, ArrowRight } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { mdxComponents } from "@/components/mdx";
import { LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { docHref, listDocs, readDoc } from "@/lib/docs";
import { SITE } from "@/lib/site";

/** 24 页 × 2 语言,全部构建期出好 —— 文档是纯静态内容,没有理由到运行时才渲染。 */
export function generateStaticParams() {
  return LOCALES.flatMap((locale) =>
    listDocs(locale).map((doc) => ({ locale, section: doc.section, name: doc.name })),
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
  const index = all.findIndex((item) => item.section === section && item.name === name);
  const prev = index > 0 ? all[index - 1] : null;
  const next = index >= 0 && index < all.length - 1 ? all[index + 1] : null;

  return (
    <article className="prose-cn font-serif">
      <header className="mb-10">
        <h1 className="mt-0 mb-3 text-3xl font-semibold sm:text-4xl">{doc.title}</h1>
        {doc.description && <p className="m-0 text-lg text-muted-foreground">{doc.description}</p>}
      </header>

      <div className="docs-body">{content}</div>

      <footer className="mt-16 border-t border-border/60 pt-6 font-sans text-sm">
        <div className="flex flex-wrap justify-between gap-4">
          {prev ? (
            <Link className="group flex items-center gap-2 text-muted-foreground hover:text-foreground" href={docHref(locale, prev)}>
              <ArrowLeft className="size-4" />
              <span>
                <span className="block text-xs">{t.prev}</span>
                {prev.title}
              </span>
            </Link>
          ) : (
            <span />
          )}
          {next && (
            <Link className="group flex items-center gap-2 text-right text-muted-foreground hover:text-foreground" href={docHref(locale, next)}>
              <span>
                <span className="block text-xs">{t.next}</span>
                {next.title}
              </span>
              <ArrowRight className="size-4" />
            </Link>
          )}
        </div>
        <p className="mt-8 mb-0 text-xs text-muted-foreground">
          <a
            className="hover:text-foreground"
            href={`${SITE.repo}/blob/main/website/content/docs/${locale as Locale}/${section}/${name}.mdx`}
            target="_blank"
            rel="noreferrer"
          >
            {t.editOnGitHub}
          </a>
        </p>
      </footer>
    </article>
  );
}
