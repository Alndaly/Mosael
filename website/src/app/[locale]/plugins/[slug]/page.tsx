import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { compileMDX } from "next-mdx-remote/rsc";
import { ArrowUpRight, Code2, KeyRound, Shield } from "lucide-react";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { PluginCard } from "@/components/community/browse";
import { ActionLink, DetailBody, DetailHeader, InfoList, Section, SideCard, Steps } from "@/components/community/detail";
import { PluginTile } from "@/components/community/tile";
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
 * README 开头那行 `# 插件名` 在 GitHub 上是标题,在这里和页头的名字重复 —— 页头已经说了
 * 这是谁,正文从第一段说明开始。
 */
function dropLeadingTitle(markdown: string): string {
  return markdown.replace(/^\s*#\s+[^\n]*\n+/, "");
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
  const t = getMessages(locale);

  const raw = readPluginDoc(slug);
  const doc = raw
    ? await compileMDX({
        source: rewriteRelativeLinks(unwrapAutolinks(dropLeadingTitle(raw)), plugin.source),
        components: mdxComponents(locale),
        options: { mdxOptions: { remarkPlugins: [remarkGfm], rehypePlugins: [rehypeSlug] } },
      })
    : null;
  // 同一类的排前面(同是对象存储、同是 MCP 接入),凑满三个。
  const more = listPlugins(locale)
    .filter((other) => other.slug !== plugin.slug)
    .sort((a, b) => Number(b.kind === plugin.kind) - Number(a.kind === plugin.kind))
    .slice(0, 3);
  const author = plugin.author.name || "—";

  return (
    <>
      <DetailHeader
        locale={locale}
        section={{ label: t.plugins.title, href: "/plugins" }}
        tile={<PluginTile seed={plugin.id} name={plugin.name} size="lg" />}
        name={plugin.name}
        author={author}
        version={`v${plugin.version}`}
        official={plugin.official}
        summary={plugin.summary}
        actions={
          <>
            {/* 深链只导航、不执行(electron/system/deepLink.ts):装过了就打开它的插件页,没装就
                打开市场、找到它 —— 装不装仍由人点。 */}
            <ActionLink href={`mosael://open?view=plugins&market=${encodeURIComponent(plugin.id)}`} primary>
              {t.community.openInApp}
            </ActionLink>
            <ActionLink href={`${SITE.repo}/tree/main/${plugin.source}`}>
              <Code2 className="size-4" aria-hidden />
              {t.community.source}
            </ActionLink>
          </>
        }
      />
      <DetailBody
        main={
          <>
            <Section id="overview" title={t.community.overview}>
              {doc ? (
                // 和文档站正文同一套排版(docs-body)—— 插件的说明不该长得像另一个网站。
                <div className="docs-body">{doc.content}</div>
              ) : (
                <p className="m-0 text-muted-foreground">{t.plugins.noDoc}</p>
              )}
            </Section>

            <Section id="tools" title={t.plugins.toolsTitle} count={plugin.tools.length || undefined}>
              {plugin.tools.length === 0 ? (
                <p className="m-0 text-sm leading-7 text-muted-foreground">{t.plugins.toolsMcpNote}</p>
              ) : (
                <ul className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
                  {plugin.tools.map((tool) => (
                    <li key={tool.name} className="grid gap-1.5 border-border px-5 py-4 not-last:border-b">
                      <code className="w-fit rounded-md bg-secondary px-2 py-0.5 font-mono text-xs font-semibold">{tool.name}</code>
                      {tool.description && <p className="m-0 text-sm leading-6 text-muted-foreground">{tool.description}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section id="permissions" title={t.plugins.permissionsTitle} count={plugin.permissions.length || undefined}>
              {plugin.permissions.length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2">
                  {plugin.permissions.map((permission) => (
                    <span key={permission} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 font-mono text-xs">
                      <Shield className="size-3.5 text-muted-foreground" aria-hidden />
                      {permission}
                    </span>
                  ))}
                </div>
              )}
              <p className="m-0 text-sm leading-7 text-muted-foreground">
                {plugin.permissions.length > 0 ? t.plugins.permissionsNote : t.plugins.noPermissionsNote}
              </p>
            </Section>
          </>
        }
        aside={
          <>
            <SideCard title={t.community.install}>
              <Steps steps={t.plugins.installSteps} />
              <p className="mt-5 mb-0 text-xs text-muted-foreground">
                {t.community.noApp}{" "}
                <a className="font-semibold text-primary hover:underline" href={localePath(locale, "/docs/start/download")}>
                  {t.community.getApp}
                </a>
              </p>
            </SideCard>

            <SideCard title={t.community.info}>
              <InfoList
                rows={[
                  {
                    label: t.community.by,
                    value: plugin.author.url ? (
                      <a className="text-primary hover:underline" href={plugin.author.url} target="_blank" rel="noreferrer">
                        {author}
                      </a>
                    ) : (
                      author
                    ),
                  },
                  { label: t.community.version, value: <span className="font-mono">v{plugin.version}</span> },
                  { label: t.community.type, value: plugin.kind === "mcp" ? t.plugins.kindMcp : t.plugins.kindScript },
                  { label: t.community.id, value: <code className="font-mono text-xs">{plugin.id}</code> },
                ]}
              />
            </SideCard>

            <SideCard title={t.plugins.credentials}>
              {plugin.credentials.length > 0 ? (
                <ul className="m-0 grid list-none gap-2 p-0 text-sm">
                  {plugin.credentials.map((credential) => (
                    <li key={credential} className="flex items-center gap-2">
                      <KeyRound className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      {credential}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="m-0 text-sm text-muted-foreground">{t.plugins.noCredentials}</p>
              )}
            </SideCard>

            <div className="grid gap-2 px-1 text-sm font-semibold">
              {plugin.homepage && (
                <a className="inline-flex items-center gap-1 text-primary hover:underline" href={plugin.homepage} target="_blank" rel="noreferrer">
                  {t.plugins.homepage}
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </a>
              )}
              <a
                className="inline-flex items-center gap-1 text-primary hover:underline"
                href={`${SITE.repo}/blob/main/docs/PLUGIN_MANIFEST.md`}
                target="_blank"
                rel="noreferrer"
              >
                {t.plugins.manifestLink}
                <ArrowUpRight className="size-3.5" aria-hidden />
              </a>
            </div>
          </>
        }
      />
      {more.length > 0 && (
        <section className="border-t border-border bg-secondary/30">
          <div className="mx-auto max-w-[76rem] px-5 py-12 sm:px-8">
            <h2 className="mt-0 mb-6 text-lg font-semibold tracking-tight">{t.plugins.more}</h2>
            <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {more.map((other) => (
                <li key={other.id} className="grid">
                  <PluginCard locale={locale} plugin={other} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
