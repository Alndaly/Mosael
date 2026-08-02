/**
 * 站点语言。
 *
 * 路由段用短码(`/zh` `/en`),`<html lang>` 用 BCP 47 —— 两者不是一回事:短码是给人看的
 * URL,lang 是给浏览器和读屏软件看的,`zh` 和 `zh-CN` 在字体回退和断词上会走不同分支。
 *
 * 中文没有做成"根路径 + /en"(Starlight 那套),是因为在 App Router 里根语言要么靠
 * middleware 重写、要么把整棵路由树写两遍;`[locale]` 段两边对称,少一类只在一种语言下
 * 复现的 bug。旧文档站的链接由 next.config 的 redirects 收口。
 */
export const LOCALES = ["zh", "en"] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "zh";

export const HTML_LANG: Record<Locale, string> = { zh: "zh-CN", en: "en" };

/** 语言切换器上的自称 —— 一律用该语言自己的写法,别翻译。 */
export const LOCALE_LABEL: Record<Locale, string> = { zh: "简体中文", en: "English" };

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/** 站内链接一律经过这里,免得漏掉语言前缀。`path` 以 `/` 开头,或空串表示首页。 */
export function localePath(locale: Locale, path = ""): string {
  return `/${locale}${path}`;
}
