import type { MetadataRoute } from "next";

import { LOCALES } from "@/i18n/config";
import { SITE } from "@/lib/site";

/**
 * 全站可抓,只挡站内搜索那份 JSON 索引:它是给浏览器里的搜索框用的,几百 KB 的正文摘录,
 * 被当成一个「页面」收录只会和真正的文档页抢排名。
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: LOCALES.map((locale) => `/${locale}/search.json`),
    },
    sitemap: `${SITE.url}/sitemap.xml`,
    host: SITE.url,
  };
}
