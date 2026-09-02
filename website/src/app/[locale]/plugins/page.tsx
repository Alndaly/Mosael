import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins } from "@/lib/registry";
import { SITE } from "@/lib/site";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).plugins;
  return { title: `${t.title} · Mosael`, description: t.lede };
}

export default async function PluginsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).plugins;
  const plugins = listPlugins(locale);

  return (
    <>
      <PageHero title={t.title} lede={t.lede} />

      {/* 两种写法:并排两块,中间一条墨线 —— 它们是二选一,不是清单。 */}
      <section className="bg-paper">
        <div className="mx-auto max-w-[88rem] px-5 pb-24 sm:px-8 sm:pb-32">
          <h2 className="mt-0 mb-14 max-w-[14ch] font-display text-[clamp(2.5rem,6vw,5rem)] leading-[0.96] font-[700] tracking-[-0.05em]">
            {t.howTitle}
          </h2>
          <div className="grid border-t border-border sm:grid-cols-2">
            {t.how.map((item, index) => (
              <Reveal
                key={item.title}
                delay={index * 80}
                className="border-border py-9 not-last:border-b sm:px-10 sm:not-last:border-r sm:not-last:border-b-0 sm:first:pl-0"
              >
                <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">
                  {String(index + 1).padStart(2, "0")}
                </p>
                <h3 className="mt-0 mb-3 font-display text-xl font-bold tracking-tight">{item.title}</h3>
                <p className="m-0 text-muted-foreground">{item.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* 权限:一整幅墨色 —— 这是插件这一页真正想让人记住的一句。 */}
      <section className="bg-[#17141f] text-[#fbf9ff]">
        <div className="mx-auto max-w-[88rem] px-5 py-24 sm:px-8 sm:py-32 lg:grid lg:grid-cols-12 lg:gap-16">
          <h2 className="mt-0 mb-6 font-display text-[clamp(2.5rem,6vw,5rem)] leading-[0.96] font-[700] tracking-[-0.05em] lg:col-span-5 lg:mb-0">
            {t.permissionsTitle}
          </h2>
          <p className="m-0 text-lg leading-8 text-white/58 lg:col-span-7">{t.permissionsBody}</p>
        </div>
      </section>

      <section className="bg-paper">
        <div className="mx-auto max-w-[88rem] px-5 py-24 sm:px-8 sm:py-32">
          <h2 className="mt-0 mb-3 max-w-[14ch] font-display text-[clamp(2.5rem,6vw,5rem)] leading-[0.96] font-[700] tracking-[-0.05em]">
            {t.officialTitle}
          </h2>
          <p className="mt-0 mb-10 text-muted-foreground">{t.officialBody}</p>

          {/* 这份列表来自仓库里真的能装的 manifest,不是另抄的一份。 */}
          <ul className="m-0 mt-14 list-none border-t border-border p-0">
            {plugins.map((plugin, index) => (
              <Reveal
                as="li"
                key={plugin.id}
                delay={index * 70}
                className="group grid gap-5 border-b border-border py-7 md:grid-cols-[minmax(14rem,0.8fr)_minmax(0,1.5fr)_auto] md:items-center"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <h3 className="m-0 font-display text-xl font-semibold tracking-[-0.02em]">
                    <Link className="hover:text-flame" href={localePath(locale, `/plugins/${plugin.slug}`)}>
                      {plugin.name}
                    </Link>
                  </h3>
                  <span className="shrink-0 rounded-full bg-brand-soft px-2.5 py-1 font-mono text-[0.65rem] font-bold tracking-wider text-primary uppercase">
                    {plugin.kind === "mcp" ? t.kindMcp : t.kindScript}
                  </span>
                </div>
                <div className="min-w-0"><p className="m-0 text-sm leading-7 text-muted-foreground">{plugin.summary}</p><p className="mt-2 mb-0 font-mono text-[0.6875rem] text-muted-foreground/70">{plugin.id} · v{plugin.version}</p></div>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs md:justify-end">
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
                    {/* 主行动是「看详情」而不是「看源码」:大多数人想知道的是它能干什么、
                        要什么权限,而不是它怎么实现的。源码链接留在详情页里。 */}
                    <Link
                      className="ml-2 inline-flex items-center gap-1 font-sans font-semibold text-primary transition-opacity hover:opacity-70"
                      href={localePath(locale, `/plugins/${plugin.slug}`)}
                    >
                      {t.detailLink}
                      <ArrowUpRight className="size-3.5" />
                    </Link>
                  </div>
              </Reveal>
            ))}
          </ul>

          <p className="mt-12 mb-0 flex flex-wrap gap-8 text-sm font-bold">
            <Link className="text-primary hover:opacity-70" href={localePath(locale, "/docs/guides/plugins")}>
              {t.guideLink}
            </Link>
            <a
              className="text-primary hover:opacity-70"
              href={`${SITE.repo}/blob/main/docs/PLUGIN_MANIFEST.md`}
              target="_blank"
              rel="noreferrer"
            >
              {t.manifestLink}
            </a>
          </p>
        </div>
      </section>
    </>
  );
}
