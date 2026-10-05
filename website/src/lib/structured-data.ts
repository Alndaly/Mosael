import { HTML_LANG, LOCALES, type Locale } from "@/i18n/config";
import { absoluteUrl, ogImage, SITE_NAME } from "@/lib/seo";
import { SITE } from "@/lib/site";

/**
 * 结构化数据(schema.org JSON-LD)。
 *
 * **只写站上看得见、仓库里查得到的事实**:没有评分、没有下载量、没有用户评价 —— 这些字段 Google 的富结果
 * 会要,但编出来的数字比没有更糟。价格 0 是真的:安装包在 GitHub Releases 免费下载;许可是专有的
 * (个人非商业免费,商用要书面授权),所以 `license` 指向 LICENSE 原文,而不是任何开源许可。
 */
export type JsonLd = Record<string, unknown>;

const ORGANIZATION_ID = `${SITE.url}/#organization`;
const WEBSITE_ID = `${SITE.url}/#website`;
const SOFTWARE_ID = `${SITE.url}/#software`;

const AUTHOR = {
  "@type": "Person",
  name: "Kinda Hall",
  alternateName: "KindaHuaX",
  // 作者本人的账号;品牌没有官方社媒号,别把它写成 Organization 的 sameAs。
  url: SITE.authorX,
};

export function organizationLd(): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": ORGANIZATION_ID,
    name: SITE_NAME,
    url: SITE.url,
    logo: absoluteUrl("/brand/mosael-icon-light.png"),
    founder: AUTHOR,
    sameAs: [SITE.repo],
  };
}

/** 多语言站点只有一个 WebSite 节点,两种语言都列进 inLanguage;描述跟着当前页的语言。 */
export function websiteLd(description: string): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    "@id": WEBSITE_ID,
    name: SITE_NAME,
    url: SITE.url,
    description,
    inLanguage: LOCALES.map((item) => HTML_LANG[item]),
    publisher: { "@id": ORGANIZATION_ID },
  };
}

export type SoftwareFacts = {
  locale: Locale;
  description: string;
  /** 一句一个能力,和首页「能做什么」那几段对得上。 */
  features: readonly string[];
  /** 站内截图路径(`/media/...`)。 */
  screenshots: readonly string[];
  keywords: readonly string[];
};

export function softwareApplicationLd({ locale, description, features, screenshots, keywords }: SoftwareFacts): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "@id": SOFTWARE_ID,
    name: SITE_NAME,
    description,
    url: absoluteUrl(`/${locale}`),
    applicationCategory: "MultimediaApplication",
    applicationSubCategory: locale === "zh" ? "AI 视频创作" : "AI video creation",
    operatingSystem: "macOS (Apple silicon), Windows 10, Windows 11",
    downloadUrl: SITE.releases,
    installUrl: absoluteUrl(`/${locale}/docs/start/download`),
    softwareHelp: { "@type": "CreativeWork", url: absoluteUrl(`/${locale}/docs/start/intro`) },
    releaseNotes: absoluteUrl(`/${locale}/changelog`),
    image: absoluteUrl(ogImage(locale).url),
    screenshot: screenshots.map((path) => absoluteUrl(path)),
    featureList: [...features],
    keywords: keywords.join(", "),
    inLanguage: LOCALES.map((item) => HTML_LANG[item]),
    isAccessibleForFree: true,
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD", url: SITE.releases },
    license: `${SITE.repo}/blob/main/LICENSE`,
    codeRepository: SITE.repo,
    author: AUTHOR,
    publisher: { "@id": ORGANIZATION_ID },
  };
}

export function faqLd(items: readonly { question: string; answer: string }[]): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: { "@type": "Answer", text: item.answer },
    })),
  };
}

/** 面包屑。`items` 的路径不带域名,最后一项是当前页。 */
export function breadcrumbLd(items: readonly { name: string; path: string }[]): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  };
}

export function techArticleLd({
  locale,
  path,
  title,
  description,
  updated,
}: {
  locale: Locale;
  path: string;
  title: string;
  description: string;
  updated: string;
}): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: title,
    description,
    url: absoluteUrl(path),
    inLanguage: HTML_LANG[locale],
    ...(updated ? { dateModified: updated } : {}),
    image: absoluteUrl(ogImage(locale).url),
    author: AUTHOR,
    publisher: { "@id": ORGANIZATION_ID },
    about: { "@id": SOFTWARE_ID },
    isPartOf: { "@id": WEBSITE_ID },
  };
}

/**
 * 写进 `<script type="application/ld+json">` 的文本。`<` 转义成 `<`:数据里出现 `</script>`
 * 时不会提前把脚本块关掉(Next 文档给的就是这一条)。
 */
export function serializeJsonLd(data: JsonLd | JsonLd[]): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
