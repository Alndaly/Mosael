import type { MetadataRoute } from "next";

import { HTML_LANG, LOCALES, type Locale } from "@/i18n/config";
import { docHref, listDocs } from "@/lib/docs";
import { SITE } from "@/lib/site";

/**
 * 站点地图。
 *
 * 每条都带 `alternates.languages` —— 中英两版是同一篇内容的两种语言,不声明的话搜索引擎
 * 会把它们当重复内容,择一收录、另一个丢掉。
 *
 * 只列**有正文的页**:`/` 是一条 307 跳转,`/<语言>/docs` 也是跳到第一篇,把跳转写进
 * sitemap 只会浪费抓取配额。
 */
type Entry = { path: (locale: Locale) => string; priority: number };

const STATIC: Entry[] = [
  { path: (locale) => `/${locale}`, priority: 1 },
  { path: (locale) => `/${locale}/plugins`, priority: 0.8 },
  { path: (locale) => `/${locale}/workflows`, priority: 0.8 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const url = (path: string) => `${SITE.url}${path}`;
  const languages = (make: (locale: Locale) => string) =>
    Object.fromEntries(LOCALES.map((locale) => [HTML_LANG[locale], url(make(locale))]));

  const pages: MetadataRoute.Sitemap = [];

  for (const entry of STATIC) {
    for (const locale of LOCALES) {
      pages.push({
        url: url(entry.path(locale)),
        priority: entry.priority,
        changeFrequency: "monthly",
        alternates: { languages: languages(entry.path) },
      });
    }
  }

  // 文档按语言各自枚举。两种语言的目录是同构的(同一批 section/name),所以 hreflang
  // 直接按当前这篇的路径去推另一种语言的地址。
  for (const locale of LOCALES) {
    for (const doc of listDocs(locale)) {
      const make = (target: Locale) => docHref(target, doc);
      pages.push({
        url: url(docHref(locale, doc)),
        priority: 0.6,
        changeFrequency: "monthly",
        alternates: { languages: languages(make) },
      });
    }
  }

  return pages;
}
