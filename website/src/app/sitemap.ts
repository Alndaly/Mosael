import type { MetadataRoute } from "next";

import { LOCALES, type Locale } from "@/i18n/config";
import { listDocs } from "@/lib/docs";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { absoluteUrl, alternatesFor } from "@/lib/seo";

/**
 * 站点地图。
 *
 * 每条都带 `alternates.languages` —— 中英两版是同一篇内容的两种语言,不声明的话搜索引擎
 * 会把它们当重复内容,择一收录、另一个丢掉。里面还有一条 `x-default`,指默认语言那版:
 * 读者的语言两条都不匹配时(比如日语),没有它搜索引擎只能自己猜发哪版。hreflang 与页面
 * `<head>` 里那份同出 {@link alternatesFor},两处不会说两套话。
 *
 * 只列**有正文的页**:`/` 是一条 307 跳转,`/<语言>/docs` 也是跳到第一篇,把跳转写进
 * sitemap 只会浪费抓取配额。插件和工作流的详情页此前不在里面 —— 它们是长尾词(「ComfyUI 插件」
 * 「带货口播 工作流」)最可能落地的页,现在逐个列出。
 */
type Entry = { path: string; priority: number; lastModified?: string };

function entries(): Entry[] {
  const list: Entry[] = [
    { path: "", priority: 1 },
    { path: "/workflows", priority: 0.8 },
    { path: "/plugins", priority: 0.8 },
    { path: "/changelog", priority: 0.6 },
  ];
  // 两种语言的文档目录是同构的(同一批 section/name),按默认语言枚举一遍即可;
  // 测试(test/seo.test.mjs)盯着这一条。
  for (const doc of listDocs("en")) {
    list.push({
      path: `/docs/${doc.section}/${doc.name}`,
      priority: doc.section === "start" ? 0.8 : 0.7,
      lastModified: doc.updated || undefined,
    });
  }
  for (const workflow of listWorkflows("en")) list.push({ path: `/workflows/${workflow.slug}`, priority: 0.6 });
  for (const plugin of listPlugins("en")) list.push({ path: `/plugins/${plugin.slug}`, priority: 0.5 });
  return list;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const pages: MetadataRoute.Sitemap = [];
  for (const entry of entries()) {
    for (const locale of LOCALES) {
      const { canonical, languages } = alternatesFor(locale as Locale, entry.path);
      pages.push({
        url: absoluteUrl(canonical),
        ...(entry.lastModified ? { lastModified: entry.lastModified } : {}),
        priority: entry.priority,
        changeFrequency: "weekly",
        alternates: {
          languages: Object.fromEntries(Object.entries(languages).map(([lang, path]) => [lang, absoluteUrl(path)])),
        },
      });
    }
  }
  return pages;
}
