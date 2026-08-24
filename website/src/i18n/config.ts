/**
 * 站点语言。
 *
 * 路由段用短码(`/en` `/zh`),`<html lang>` 用 BCP 47 —— 两者不是一回事:短码是给人看的
 * URL,lang 是给浏览器和读屏软件看的,`zh` 和 `zh-CN` 在字体回退和断词上会走不同分支。
 *
 * 默认语言没有做成"根路径 + /zh"(Starlight 那套),是因为在 App Router 里根语言要么靠
 * middleware 重写、要么把整棵路由树写两遍;`[locale]` 段两边对称,少一类只在一种语言下
 * 复现的 bug。`/` 由 next.config 的 redirects 收口到默认语言。
 *
 * 数组顺序即语言切换器的顺序,也是 generateStaticParams 的顺序 —— 默认语言排头一个。
 */
export const LOCALES = ["en", "zh"] as const;

export type Locale = (typeof LOCALES)[number];

/**
 * 英文是默认语言:这是个面向公开互联网的开源项目,进来的人默认读英文;中文读者点一下
 * 切换即可,且切换记在 URL 里,分享出去的链接自带语言。
 */
export const DEFAULT_LOCALE: Locale = "en";

export const HTML_LANG: Record<Locale, string> = { en: "en", zh: "zh-CN" };

/** 语言切换器上的自称 —— 一律用该语言自己的写法,别翻译。 */
export const LOCALE_LABEL: Record<Locale, string> = {
  en: "English",
  zh: "简体中文",
};

/** 顶栏那颗方块按钮塞不下"简体中文",用两个字母的短码。 */
export const LOCALE_SHORT: Record<Locale, string> = { en: "EN", zh: "中" };

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/** 站内链接一律经过这里,免得漏掉语言前缀。`path` 以 `/` 开头,或空串表示首页。 */
export function localePath(locale: Locale, path = ""): string {
  return `/${locale}${path}`;
}
