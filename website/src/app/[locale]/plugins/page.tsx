import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins } from "@/lib/registry";
import { SITE } from "@/lib/site";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).plugins;
  return { title: `${t.title} · Open Studio`, description: t.lede };
}

export default async function PluginsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).plugins;
  const plugins = listPlugins();

  return (
    <div className="prose-cn mx-auto max-w-3xl px-6 py-16 font-serif sm:px-8">
      <h1 className="mt-0 mb-5 text-3xl font-semibold sm:text-4xl">{t.title}</h1>
      <p className="mt-0 mb-12 max-w-(--measure) text-lg text-muted-foreground">{t.lede}</p>

      <h2 className="mt-0 mb-6 text-2xl font-semibold">{t.howTitle}</h2>
      <div className="mb-4 grid gap-6 sm:grid-cols-2">
        {t.how.map((item) => (
          <div key={item.title}>
            <h3 className="mt-0 mb-2 text-base font-semibold">{item.title}</h3>
            <p className="m-0 text-muted-foreground">{item.body}</p>
          </div>
        ))}
      </div>

      <h2 className="mt-16 mb-4 text-2xl font-semibold">{t.permissionsTitle}</h2>
      <p className="mt-0 mb-0 max-w-(--measure) text-muted-foreground">{t.permissionsBody}</p>

      <h2 className="mt-16 mb-3 text-2xl font-semibold">{t.officialTitle}</h2>
      <p className="mt-0 mb-8 text-muted-foreground">{t.officialBody}</p>

      {/* 这份列表来自仓库里真的能装的 manifest,不是另抄的一份。 */}
      <ul className="m-0 list-none border-t border-border/60 p-0">
        {plugins.map((plugin) => (
          <li key={plugin.id} className="m-0 border-b border-border/60 py-6">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="m-0 text-lg font-semibold">{plugin.name}</h3>
              <code className="font-mono text-xs text-muted-foreground">{plugin.id}</code>
              <Badge variant="secondary" className="font-sans text-xs">
                {plugin.kind === "mcp" ? t.kindMcp : t.kindScript}
              </Badge>
              <span className="font-sans text-xs text-muted-foreground">v{plugin.version}</span>
            </div>
            <p className="mt-3 mb-4 max-w-(--measure) text-muted-foreground">{plugin.summary}</p>
            <div className="flex flex-wrap items-center gap-2 font-sans text-xs">
              {plugin.permissions.length === 0 ? (
                <span className="text-muted-foreground">{t.noPermissions}</span>
              ) : (
                plugin.permissions.map((permission) => (
                  <code key={permission} className="rounded-sm bg-muted px-1.5 py-0.5 font-mono">
                    {permission}
                  </code>
                ))
              )}
              <a
                className="ml-auto text-muted-foreground underline underline-offset-4 hover:text-foreground"
                href={`${SITE.repo}/tree/main/${plugin.source}`}
                target="_blank"
                rel="noreferrer"
              >
                {t.viewSource}
              </a>
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-10 mb-0 flex flex-wrap gap-6 font-sans text-sm">
        <Link className="underline underline-offset-4" href={localePath(locale, "/docs/guides/plugins")}>
          {t.guideLink}
        </Link>
        <a
          className="underline underline-offset-4"
          href={`${SITE.repo}/blob/main/docs/PLUGIN_MANIFEST.md`}
          target="_blank"
          rel="noreferrer"
        >
          {t.manifestLink}
        </a>
      </p>
    </div>
  );
}
