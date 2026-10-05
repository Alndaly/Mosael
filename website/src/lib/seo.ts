import type { Metadata } from "next";

import { DEFAULT_LOCALE, HTML_LANG, LOCALES, type Locale } from "@/i18n/config";
import { SITE } from "@/lib/site";

/**
 * 每一页的 `<head>` 从这里出:标题、描述、关键词、canonical、hreflang、Open Graph、Twitter 卡片。
 *
 * **为什么不放在根布局里继承**:Next 的 metadata 按字段整块覆盖、没覆盖的整块继承。此前根布局写了
 * `alternates.canonical = /<语言>` 和一份首页的 `openGraph`,插件页、工作流页、更新日志没写自己的 ——
 * 于是它们全都声明「我的规范地址是首页」,分享出去的卡片也是首页的标题。搜索引擎读到 canonical 指向
 * 别处,就把这一页当首页的重复,不收录。现在根布局不再写这两块,每一页都经过 {@link pageMetadata},
 * 测试(test/seo.test.mjs)盯着每个 page.tsx 都调用了它。
 */

export const SITE_NAME = "Mosael";

/** Open Graph 的 locale 用下划线(`zh_CN`),和 `<html lang>` 的 BCP 47(`zh-CN`)不是一种写法。 */
export const OG_LOCALE: Record<Locale, string> = { en: "en_US", zh: "zh_CN" };

/** 标题后缀。页面自己的词放前面 —— 搜索结果标题被截断时,截掉的是品牌名而不是关键词。 */
export function withSiteName(title: string): string {
  return title.includes(SITE_NAME) ? title : `${title} | ${SITE_NAME}`;
}

/**
 * 一页在各语言下的地址。`path` 不带语言前缀,以 `/` 开头;首页是空串。
 *
 * hreflang 的键用 `<html lang>` 那一套(`en`、`zh-CN`),外加 `x-default` 指默认语言那版 ——
 * 读者的语言两种都不是时(比如日语),搜索引擎发这一版,而不是自己猜。
 */
export function alternatesFor(locale: Locale, path: string) {
  return {
    canonical: `/${locale}${path}`,
    languages: {
      ...Object.fromEntries(LOCALES.map((item) => [HTML_LANG[item], `/${item}${path}`])),
      "x-default": `/${DEFAULT_LOCALE}${path}`,
    },
  };
}

/**
 * 分享卡片用的图:首页那三张实拍截图叠成的一张(scripts/compose-readme-showcase.py 生成,
 * 和 README 顶上那张同源),1200×630 —— 各家卡片都按这个比例裁。
 */
export function ogImage(locale: Locale) {
  return {
    url: `/og/mosael-${locale}.png`,
    width: 1200,
    height: 630,
    alt:
      locale === "zh"
        ? "Mosael 界面实拍:创意画板、剪辑时间线与 3D 场景叠放"
        : "Mosael screenshots: idea board, editing timeline and a 3D scene, layered",
  };
}

/**
 * 从数据(插件简介、工作流简介)截 meta 描述时的上限。搜索结果只显示前一百多个字符,
 * 工作流简介动辄四五百字,原样塞进去只会在中间被截断。
 */
export const META_DESCRIPTION_MAX = 150;

export type PageSeo = {
  locale: Locale;
  /** 不带语言前缀的路径,首页传 `""`。 */
  path: string;
  /** 页面自己的标题;品牌名由 {@link withSiteName} 补,已经带了就不再补。 */
  title: string;
  description: string;
  /** 百度仍读 `<meta name="keywords">`;Google 不用它,但也不扣分。 */
  keywords?: readonly string[];
  type?: "website" | "article";
};

export function pageMetadata({ locale, path, title, description, keywords, type = "website" }: PageSeo): Metadata {
  const fullTitle = withSiteName(title);
  const image = ogImage(locale);
  return {
    title: { absolute: fullTitle },
    description,
    ...(keywords?.length ? { keywords: [...keywords] } : {}),
    alternates: alternatesFor(locale, path),
    openGraph: {
      type,
      siteName: SITE_NAME,
      title: fullTitle,
      description,
      url: `/${locale}${path}`,
      locale: OG_LOCALE[locale],
      alternateLocale: LOCALES.filter((item) => item !== locale).map((item) => OG_LOCALE[item]),
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description,
      // 作者本人的账号,不是品牌官方号(见 website/README.md 的约定)。
      creator: "@KindaHuaX",
      images: [{ url: image.url, alt: image.alt }],
    },
  };
}

/**
 * 站长平台的验证码。**这里不写任何真值** —— 验证码是维护者在各家平台上领的,从部署环境读;
 * 没配的那家不出 meta。键是 meta 的 name,值是环境变量名(见 website/.env.example 与 docs/SEO.md)。
 */
export const VERIFICATION_ENV = {
  google: "SITE_VERIFICATION_GOOGLE",
  "baidu-site-verification": "SITE_VERIFICATION_BAIDU",
  "msvalidate.01": "SITE_VERIFICATION_BING",
  "360-site-verification": "SITE_VERIFICATION_360",
  sogou_site_verification: "SITE_VERIFICATION_SOGOU",
} as const;

export function siteVerification(env: Record<string, string | undefined>): Metadata["verification"] {
  const read = (name: string) => env[name]?.trim() || undefined;
  const google = read(VERIFICATION_ENV.google);
  const other: Record<string, string> = {};
  for (const [meta, variable] of Object.entries(VERIFICATION_ENV)) {
    if (meta === "google") continue;
    const value = read(variable);
    if (value) other[meta] = value;
  }
  if (!google && Object.keys(other).length === 0) return undefined;
  return { ...(google ? { google } : {}), ...(Object.keys(other).length ? { other } : {}) };
}

/** 绝对地址:JSON-LD 和 sitemap 里不能写相对路径。 */
export function absoluteUrl(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${SITE.url}${path.startsWith("/") ? path : `/${path}`}`;
}
