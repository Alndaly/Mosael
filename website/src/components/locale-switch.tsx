"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LOCALE_SHORT, LOCALES, type Locale } from "@/i18n/config";

/**
 * 语言切换。
 *
 * 换掉路径里的第一段而不是一律跳回首页 —— 读到指南第三节的人切成英文,应该还在第三节。
 * 目标页缺失时会 404,这是双语站的老问题;当前 24 页是同构的,等社区页开始出现单语内容
 * 再考虑回退。
 */
export function LocaleSwitch({ locale, label }: { locale: Locale; label: string }) {
  const pathname = usePathname();
  const other = LOCALES.find((item) => item !== locale) ?? locale;
  const rest = pathname.split("/").slice(2).join("/");

  return (
    <Link
      href={`/${other}${rest ? `/${rest}` : ""}`}
      hrefLang={other}
      aria-label={label}
      title={label}
      className="inline-flex h-9 items-center justify-center rounded-lg px-2.5 text-xs font-semibold uppercase text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    >
      {LOCALE_SHORT[other]}
    </Link>
  );
}
