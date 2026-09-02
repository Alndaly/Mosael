import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { mdxComponents } from "@/components/mdx";
import { LOCALES, isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { findPlugin, listPlugins, readPluginDoc } from "@/lib/registry";
import { SITE } from "@/lib/site";

/** 每个插件 × 每种语言,构建期全出好 —— 数据来自仓库里的文件,没有理由到运行时才读。 */
export function generateStaticParams() {
  return LOCALES.flatMap((locale) => listPlugins().map((plugin) => ({ locale, slug: plugin.slug })));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  const plugin = findPlugin(slug, isLocale(locale) ? locale : undefined);
  if (!plugin) return {};
  return {
    title: `${plugin.name} · ${getMessages(isLocale(locale) ? locale : "en").plugins.title}`,
    description: plugin.summary,
  };
}

/**
 * `<https://…>` 是合法的 markdown(autolink),但 **MDX 会把它当成 JSX 标签**,直接编译失败。
 *
 * README 是给人写的、也要在 GitHub 上好看,不该为了我们的渲染器改写法 —— 所以在这里
 * 转成普通链接。这不是"容错",是两种方言之间的翻译:markdown 认 autolink,MDX 不认。
 */
function unwrapAutolinks(markdown: string): string {
  return markdown.replace(/<(https?:\/\/[^\s>]+)>/g, "[$1]($1)");
}

/**
 * README 里的相对链接**在网页上是坏的**。
 *
 * 那些路径是按仓库目录写的(`../../../docs/PLUGIN_MANIFEST.md`),在 GitHub 上点得开,
 * 搬到 /plugins/<slug> 这个地址下就指向了不存在的地方。渲染前统一改指回仓库 ——
 * 不改的话,详情页上每一个「见 xxx」都是 404,而写 README 的人完全不知情。
 */
function rewriteRelativeLinks(markdown: string, source: string): string {
  return markdown.replace(/\]\((?!https?:\/\/|#)([^)]+)\)/g, (match, target: string) => {
    const cleaned = String(target).trim();
    if (cleaned.startsWith("/")) return match;
    const resolved = new URL(cleaned, `https://x/${source}/`).pathname.replace(/^\//, "");
    return `](${SITE.repo}/blob/main/${resolved})`;
  });
}

export default async function PluginDetailPage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const plugin = findPlugin(slug, locale);
  if (!plugin) notFound();
  const t = getMessages(locale).plugins;

  const raw = readPluginDoc(slug);
  const doc = raw
    ? await compileMDX({
        source: rewriteRelativeLinks(unwrapAutolinks(raw), plugin.source),
        components: mdxComponents(locale),
        options: { mdxOptions: { remarkPlugins: [remarkGfm], rehypePlugins: [rehypeSlug] } },
      })
    : null;

  return (
    <div className="bg-paper">
      <div className="relative isolate overflow-hidden px-5 pt-16 pb-18 sm:px-8 sm:pt-24 sm:pb-24">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_12%_20%,rgba(114,87,233,0.15),transparent_34%),radial-gradient(circle_at_88%_0%,rgba(255,139,120,0.13),transparent_30%)]" />
        <div className="mx-auto max-w-[76rem]">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-primary"
          href={localePath(locale, "/plugins")}
        >
          <ArrowLeft className="size-4" />
          {t.backToList}
        </Link>

        <header className="mt-10">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="m-0 font-display text-[clamp(3rem,7vw,6rem)] leading-[0.92] font-[720] tracking-[-0.055em]">
              {plugin.name}
            </h1>
            <span className="shrink-0 rounded-full bg-brand-soft px-3 py-1 font-mono text-[0.65rem] font-bold tracking-wider text-primary uppercase">
              {plugin.kind === "mcp" ? t.kindMcp : t.kindScript}
            </span>
          </div>
          <p className="mt-3 mb-0 font-mono text-xs text-muted-foreground">
            {plugin.id} · v{plugin.version}
          </p>
          <p className="mt-6 mb-0 max-w-[52rem] text-lg leading-8 text-muted-foreground">{plugin.summary}</p>
        </header>
        </div>
      </div>

      <div className="mx-auto grid max-w-[76rem] gap-12 px-5 py-20 sm:px-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="min-w-0">
            <h2 className="mt-0 mb-4 font-display text-2xl font-extrabold tracking-tight">{t.docTitle}</h2>
            {doc ? (
              // 和文档站正文同一套排版(docs-body)—— 插件的说明不该长得像另一个网站。
              <div className="docs-body">{doc.content}</div>
            ) : (
              <p className="m-0 text-muted-foreground">{t.noDoc}</p>
            )}
          </div>

          <aside className="grid content-start gap-8 border-t border-border pt-8 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8">
            <section>
              <h2 className="mt-0 mb-3 font-display text-lg font-extrabold tracking-tight">{t.permissionsTitle}</h2>
              <div className="flex flex-wrap gap-2 font-mono text-xs">
                {plugin.permissions.length === 0 ? (
                  <span className="text-muted-foreground">
                    {t.noPermissions}
                  </span>
                ) : (
                  plugin.permissions.map((permission) => (
                    <span key={permission} className="rounded-full bg-secondary px-2.5 py-1 text-muted-foreground">
                      {permission}
                    </span>
                  ))
                )}
              </div>
            </section>

            <section>
              <h2 className="mt-0 mb-3 font-display text-lg font-extrabold tracking-tight">{t.toolsTitle}</h2>
              {plugin.tools.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">{t.toolsMcpNote}</p>
              ) : (
                <ul className="m-0 grid list-none gap-3 p-0">
                  {plugin.tools.map((tool) => (
                    <li key={tool.name}>
                      <code className="font-mono text-xs font-bold">{tool.name}</code>
                      {tool.description && (
                        <p className="mt-1 mb-0 text-sm leading-relaxed text-muted-foreground">{tool.description}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h2 className="mt-0 mb-3 font-display text-lg font-extrabold tracking-tight">{t.installTitle}</h2>
              <p className="m-0 text-sm leading-relaxed text-muted-foreground">{t.installBody}</p>
            </section>

            <a
              className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:opacity-70"
              href={`${SITE.repo}/tree/main/${plugin.source}`}
              target="_blank"
              rel="noreferrer"
            >
              {t.viewSource}
              <ArrowUpRight className="size-3.5" />
            </a>
          </aside>
      </div>
    </div>
  );
}
