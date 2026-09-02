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
      <section className="border-b-2 border-ink bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8">
          <h2 className="mt-0 mb-12 font-display text-[clamp(1.5rem,4vw,2.75rem)] font-extrabold tracking-tight">
            {t.howTitle}
          </h2>
          <div className="grid border-2 border-ink sm:grid-cols-2">
            {t.how.map((item, index) => (
              <Reveal
                key={item.title}
                delay={index * 80}
                className="border-ink p-8 not-last:border-b-2 sm:not-last:border-r-2 sm:not-last:border-b-0"
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
      <section className="border-b-2 border-ink bg-invert text-invert-foreground">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8 lg:grid lg:grid-cols-12 lg:gap-16">
          <h2 className="mt-0 mb-6 font-display text-[clamp(1.5rem,4vw,2.75rem)] leading-tight font-extrabold tracking-tight lg:col-span-5 lg:mb-0">
            {t.permissionsTitle}
          </h2>
          <p className="m-0 text-lg text-invert-foreground/70 lg:col-span-7">{t.permissionsBody}</p>
        </div>
      </section>

      <section className="bg-paper">
        <div className="mx-auto max-w-[96rem] px-5 py-20 sm:px-8">
          <h2 className="mt-0 mb-3 font-display text-[clamp(1.5rem,4vw,2.75rem)] font-extrabold tracking-tight">
            {t.officialTitle}
          </h2>
          <p className="mt-0 mb-10 text-muted-foreground">{t.officialBody}</p>

          {/* 这份列表来自仓库里真的能装的 manifest,不是另抄的一份。 */}
          <ul className="m-0 grid list-none gap-6 p-0 lg:grid-cols-3">
            {plugins.map((plugin, index) => (
              <Reveal
                as="li"
                key={plugin.id}
                delay={index * 70}
                className="flex flex-col border-2 border-ink bg-card transition-shadow hover:shadow-block"
              >
                <div className="flex items-center gap-3 border-b-2 border-ink px-6 py-4">
                  <h3 className="m-0 font-display text-lg font-bold tracking-tight">
                    <Link className="hover:text-flame" href={localePath(locale, `/plugins/${plugin.slug}`)}>
                      {plugin.name}
                    </Link>
                  </h3>
                  <span className="ml-auto shrink-0 border-2 border-ink px-2 py-0.5 font-mono text-[0.65rem] font-bold tracking-wider uppercase">
                    {plugin.kind === "mcp" ? t.kindMcp : t.kindScript}
                  </span>
                </div>
                <div className="flex flex-1 flex-col gap-4 p-6">
                  <p className="m-0 font-mono text-xs text-muted-foreground">
                    {plugin.id} · v{plugin.version}
                  </p>
                  <p className="m-0 flex-1 text-muted-foreground">{plugin.summary}</p>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                    {plugin.permissions.length === 0 ? (
                      <span className="border-2 border-dashed border-muted-foreground/40 px-2 py-0.5 text-muted-foreground">
                        {t.noPermissions}
                      </span>
                    ) : (
                      plugin.permissions.map((permission) => (
                        <span key={permission} className="bg-ink px-2 py-0.5 text-paper">
                          {permission}
                        </span>
                      ))
                    )}
                    {/* 主行动是「看详情」而不是「看源码」:大多数人想知道的是它能干什么、
                        要什么权限,而不是它怎么实现的。源码链接留在详情页里。 */}
                    <Link
                      className="ml-auto inline-flex items-center gap-1 font-sans font-bold text-flame hover:underline"
                      href={localePath(locale, `/plugins/${plugin.slug}`)}
                    >
                      {t.detailLink}
                      <ArrowUpRight className="size-3.5" />
                    </Link>
                  </div>
                </div>
              </Reveal>
            ))}
          </ul>

          <p className="mt-12 mb-0 flex flex-wrap gap-8 text-sm font-bold">
            <Link className="border-b-2 border-flame pb-0.5" href={localePath(locale, "/docs/guides/plugins")}>
              {t.guideLink}
            </Link>
            <a
              className="border-b-2 border-flame pb-0.5"
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
