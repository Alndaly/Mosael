import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PluginBrowser } from "@/components/community/browse";
import { CommunityHeader } from "@/components/community/community-header";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).plugins;
  // 描述带上已收录的插件名:「ComfyUI 插件」「Blender MCP」这类搜索落到这一页,名字得在摘要里。
  const names = listPlugins(locale).map((plugin) => plugin.name);
  return pageMetadata({
    locale,
    path: "/plugins",
    title: t.seoTitle,
    description: `${t.lede} ${t.seoIncludes}${names.join(locale === "zh" ? "、" : ", ")}`,
    keywords: t.keywords,
  });
}

export default async function PluginsPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).plugins;
  // 列表来自仓库里真的能装的 manifest,不是另抄的一份(见 lib/registry)。
  const plugins = listPlugins(locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        active="plugins"
        counts={{ plugins: plugins.length, workflows: listWorkflows(locale).length }}
        title={t.heading}
        lede={t.lede}
        contribute={{ label: t.contribute, href: localePath(locale, "/docs/guides/writing-plugins") }}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <PluginBrowser locale={locale} plugins={plugins} />
        </div>
      </section>
    </>
  );
}
